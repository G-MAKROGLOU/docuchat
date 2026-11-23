// The browser calls the backend only through the frontend proxy under this prefix.
export const API_BASE = "/api/v1";

// A hung backend gives an error after this time, not an endless spinner.
// A settings save checks the model list and rebuilds services, so it can take a while.
const TIMEOUT_MS = 30_000;

class ApiError extends Error {
  constructor(
    readonly method: string,
    readonly path: string,
    readonly status: number,
  ) {
    super(`${method} ${path} returned ${status}`);
    this.name = "ApiError";
  }
}

// Runs `call` with a signal that aborts on the caller signal or after TIMEOUT_MS.
async function withTimeout<T>(
  signal: AbortSignal | undefined,
  call: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timer = setTimeout(abort, TIMEOUT_MS);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort);
  try {
    return await call(controller.signal);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return withTimeout(signal, async (combined) => {
    const response = await fetch(`${API_BASE}${path}`, { signal: combined });
    if (!response.ok) throw new ApiError("GET", path, response.status);
    return (await response.json()) as T;
  });
}

type Sent = { status: number; body: unknown };

// A GET whose error status is an answer too, such as a 503 from a health check.
export function probeJson(path: string, signal?: AbortSignal): Promise<Sent> {
  return withTimeout(signal, async (combined) => {
    const response = await fetch(`${API_BASE}${path}`, { signal: combined });
    const json = response.headers.get("content-type")?.includes("application/json");
    return { status: response.status, body: json ? await response.json() : null };
  });
}

// The caller maps the status to its own outcome. The body is null when it is not JSON.
export function sendJson(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<Sent> {
  return withTimeout(signal, async (combined) => {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      ...(body === undefined
        ? {}
        : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
      signal: combined,
    });
    const json = response.headers.get("content-type")?.includes("application/json");
    return { status: response.status, body: json ? await response.json() : null };
  });
}

// For a streamed response: the timeout covers the wait for the headers only, and the caller
// signal stays connected while the body streams.
export async function postStream(
  path: string,
  body: unknown,
  signal: AbortSignal,
): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) abort();
  else signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new ApiError("POST", path, response.status);
    return response;
  } catch (error) {
    signal.removeEventListener("abort", abort);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
