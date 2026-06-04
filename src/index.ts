import { getSandbox } from "@cloudflare/sandbox";
export { Sandbox } from "@cloudflare/sandbox";

const MAX_RETRIES = 15;
const RETRY_DELAY_MS = 2000;

export default {
  async fetch(request: Request, env: any): Promise<Response> {
    const container = getSandbox(env.png2font, "global-session");

    const targetUrl = new URL(request.url);
    targetUrl.protocol = "http:";
    targetUrl.host = "localhost:3000";

    // Buffer body once so we can replay it on retries
    const bodyBuffer = request.body ? await request.arrayBuffer() : null;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      const response = await container.fetch(targetUrl.toString(), {
        method: request.method,
        headers: request.headers,
        body: bodyBuffer,
      });

      if (response.status !== 503) {
        return response;
      }

      // Only retry on container startup 503s
      const cloned = response.clone();
      const json = await cloned.json().catch(() => null) as any;
      if (json?.context?.phase !== "startup") {
        return response;
      }

      if (attempt < MAX_RETRIES) {
        await new Promise(r => setTimeout(r, RETRY_DELAY_MS));
      }
    }

    return new Response(
      JSON.stringify({ error: "Container failed to start after retries" }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  },
};
