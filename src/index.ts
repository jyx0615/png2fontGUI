import { getSandbox } from "@cloudflare/sandbox";
export { Sandbox } from "@cloudflare/sandbox";

// Configuration constants for container startup retry logic
const MAX_RETRIES = 15;
const RETRY_DELAY_MS = 2000;
const LOCAL_SERVER_PORT = 3000;
const LOCAL_SERVER_PROTOCOL = "http:";
const STARTUP_ERROR_STATUS = 503;
const STARTUP_PHASE = "startup";
const JSON_CONTENT_TYPE = "application/json";

/**
 * Converts an incoming request URL to target the local container server.
 * @param originalUrl - The original request URL
 * @returns URL pointing to the local container server
 */
function buildContainerRequestUrl(originalUrl: string): string {
  const targetUrl = new URL(originalUrl);
  targetUrl.protocol = LOCAL_SERVER_PROTOCOL;
  targetUrl.host = `localhost:${LOCAL_SERVER_PORT}`;
  return targetUrl.toString();
}

/**
 * Checks if a 503 response indicates a container startup error that warrants retrying.
 * @param response - The 503 response to check
 * @returns true if the error is a startup phase error, false otherwise
 */
async function isStartupPhaseError(response: Response): Promise<boolean> {
  const cloned = response.clone();
  const json = await cloned.json().catch(() => null) as any;
  return json?.context?.phase === STARTUP_PHASE;
}

/**
 * Waits for a specified delay (used between retry attempts).
 * @param delayMs - The delay duration in milliseconds
 */
function delay(delayMs: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, delayMs));
}

/**
 * Creates a standardized error response for container startup failures.
 * @returns Response object with error message and 503 status
 */
function createContainerStartupErrorResponse(): Response {
  return new Response(
    JSON.stringify({ error: "Container failed to start after retries" }),
    { status: STARTUP_ERROR_STATUS, headers: { "Content-Type": JSON_CONTENT_TYPE } }
  );
}

export default {
  /**
   * Handles incoming HTTP requests by forwarding them to a containerized server.
   * Automatically retries requests on container startup failures (503 status).
   *
   * Flow:
   * 1. Route the request to the local container server
   * 2. If response is not 503, return it immediately
   * 3. If 503 is due to startup phase, retry with exponential backoff
   * 4. If max retries exceeded, return a startup error response
   *
   * @param request - The incoming HTTP request
   * @param env - Environment variables containing container configuration
   * @returns The response from the container, or an error response if startup fails
   */
  async fetch(request: Request, env: any): Promise<Response> {
    // Initialize the containerized application
    const container = getSandbox(env.png2font, "global-session");

    // Prepare the request body for potential retries (clone it once to avoid stream issues)
    const bodyBuffer = request.body ? await request.arrayBuffer() : null;

    // Attempt to forward the request, retrying on container startup failures
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      const containerUrl = buildContainerRequestUrl(request.url);

      const response = await container.fetch(containerUrl, {
        method: request.method,
        headers: request.headers,
        body: bodyBuffer,
      });

      // Return immediately if request succeeded or failed for a non-startup reason
      if (response.status !== STARTUP_ERROR_STATUS) {
        return response;
      }

      // Check if this 503 is specifically due to the container starting up
      if (!(await isStartupPhaseError(response))) {
        return response;
      }

      // If retries remain, wait before attempting again
      if (attempt < MAX_RETRIES) {
        await delay(RETRY_DELAY_MS);
      }
    }

    // All retries exhausted; return startup error
    return createContainerStartupErrorResponse();
  },
};
