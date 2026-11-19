// Forwards /api/* to ${BACKEND_URL}/api/*. The response body is streamed through without buffering.
export const dynamic = "force-dynamic";

const HEADERS_TIMEOUT_MS = 10_000;
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
  const search = new URL(request.url).search;
  const target = `${process.env.BACKEND_URL}/api/${path.map(encodeURIComponent).join("/")}${search}`;

  // The timeout covers the wait for response headers only, so long streams are not cut.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HEADERS_TIMEOUT_MS);
  request.signal.addEventListener("abort", () => controller.abort());

  let upstream: Response;
  try {
    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    upstream = await fetch(target, {
      method: request.method,
      headers: copyHeaders(request.headers),
      body: hasBody ? request.body : undefined,
      duplex: "half",
      signal: controller.signal,
      cache: "no-store",
      redirect: "manual",
    } as RequestInit);
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }

  const headers = copyHeaders(upstream.headers);
  if (headers.get("content-type")?.startsWith("text/event-stream")) {
    headers.set("cache-control", "no-cache, no-transform");
    headers.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
