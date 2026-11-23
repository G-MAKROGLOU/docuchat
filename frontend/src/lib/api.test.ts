import { afterEach, describe, expect, it, vi } from "vitest";
import { getJson, sendJson } from "./api";

// A fetch that answers only when its signal aborts.
function hangingFetch(_url: string, init?: RequestInit): Promise<Response> {
  return new Promise((_, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
  });
}

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("prefixes the path and throws on an error status", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJson("/status")).rejects.toThrow("GET /status returned 500");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/status");
  });

  it("gives up on a hung backend after the timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(hangingFetch));

    const result = getJson("/status").catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(await result).toEqual(new Error("aborted"));
  });

  it("aborts with the caller signal", async () => {
    vi.stubGlobal("fetch", vi.fn(hangingFetch));
    const controller = new AbortController();

    const result = sendJson("POST", "/ingestion", undefined, controller.signal);
    controller.abort();
    await expect(result).rejects.toThrow("aborted");
  });

  it("returns the status and the JSON body of a write", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ detail: "x" }, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await sendJson("PUT", "/settings", { a: 1 })).toEqual({
      status: 409,
      body: { detail: "x" },
    });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(init?.body).toBe('{"a":1}');
  });
});
