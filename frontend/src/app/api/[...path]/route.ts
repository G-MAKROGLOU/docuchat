// Forwards /api/* to ${BACKEND_URL}/api/*. The response body is streamed through without buffering.
export const dynamic = "force-dynamic";

// Longer than the client timeout in lib/api.ts, so the client decides and gets no early 504.
const HEADERS_TIMEOUT_MS = 35_000;
// Hop-by-hop headers, plus encodings that fetch has already decoded.
const SKIPPED_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-connection",
  "transfer-encoding",
  "upgrade",
  "te",
  "trailer",
  "host",
  "content-length",
  "content-encoding",
  "accept-encoding",
]);

type Context = { params: Promise<{ path: string[] }> };

function copyHeaders(source: Headers): Headers {
  const target = new Headers();
  source.forEach((value, key) => {
    if (!SKIPPED_HEADERS.has(key)) target.set(key, value);
  });
  return target;
}

async function proxy(request: Request, context: Context): Promise<Response> {
  const { path } = await context.params;
  const backendUrl = process.env.BACKEND_URL;
  // Fail with a clear message, not with a request to "undefined/api/...".
  if (!backendUrl) throw new Error("BACKEND_URL is not set.");
  const url = new URL(request.url);
  const target = `${backendUrl}/api/${path.map(encodeURIComponent).join("/")}${url.search}`;

  // The timeout covers the wait for response headers only, so long streams are not cut.
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, HEADERS_TIMEOUT_MS);
  // Stays while the body streams, so a closed browser request also stops the backend stream.
  request.signal.addEventListener("abort", () => controller.abort(), { once: true });

  const headers = copyHeaders(request.headers);
  // The backend logs then show the host and scheme that the browser used.
  if (!headers.has("x-forwarded-host")) headers.set("x-forwarded-host", url.host);
  if (!headers.has("x-forwarded-proto"))
    headers.set("x-forwarded-proto", url.protocol.slice(0, -1));

  let upstream: Response;
  try {
    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      duplex: "half",
      signal: controller.signal,
      cache: "no-store",
      redirect: "manual",
    } as RequestInit);
  } catch {
    if (timedOut) return Response.json({ error: "backend_timeout" }, { status: 504 });
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }

  const responseHeaders = copyHeaders(upstream.headers);
  // A redirect to the backend host becomes a relative URL, so the browser stays on the frontend.
  const location = responseHeaders.get("location");
  if (location) {
    const backend = new URL(backendUrl);
    const resolved = new URL(location, backend);
    if (resolved.origin === backend.origin)
      responseHeaders.set("location", resolved.pathname + resolved.search);
  }
  if (responseHeaders.get("content-type")?.startsWith("text/event-stream")) {
    responseHeaders.set("cache-control", "no-cache, no-transform");
    responseHeaders.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export {
  proxy as DELETE,
  proxy as GET,
  proxy as HEAD,
  proxy as OPTIONS,
  proxy as PATCH,
  proxy as POST,
  proxy as PUT,
};
