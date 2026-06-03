import { getSandbox } from "@cloudflare/sandbox";
export { Sandbox } from "@cloudflare/sandbox";

export default {
  async fetch(request: Request, env: any): Promise<Response> {
    // 1. Instantiates or resumes your Docker container on the edge network
    // Change "global-session" to isolate instances per user if needed
    const container = getSandbox(env.png2font, "global-session");

    // 2. Clone the incoming request URL to point inside the container's internal port
    // Change 8080 to match whatever port your Dockerfile exposes
    const targetUrl = new URL(request.url);
    targetUrl.protocol = "http:";
    targetUrl.host = "localhost:8000";

    // 3. Forward the incoming HTTP request directly into your running container
    return await container.fetch(targetUrl.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.body,
    });
  },
};
