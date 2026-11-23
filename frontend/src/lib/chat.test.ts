import { afterEach, describe, expect, it, vi } from "vitest";
import type { Source } from "@/lib/contract/generated";
import { endConversation, readEvents, sourceLabel, withSources } from "./chat";

function streamOf(...parts: string[]): ReadableStream<Uint8Array<ArrayBuffer>> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
}

describe("readEvents", () => {
  it("parses events split across chunks", async () => {
    const body = streamOf(
      'data: {"type":"token","text":"Hel',
      'lo"}\n\ndata: {"type":"final","answer":"Hello","citations":[]}\n',
      "\n",
    );
    const events = [];
    for await (const event of readEvents(body)) events.push(event);
    expect(events).toEqual([
      { type: "token", text: "Hello" },
      { type: "final", answer: "Hello", citations: [] },
    ]);
  });

  it("skips a malformed block and keeps reading", async () => {
    const body = streamOf('data: {"type":"tok\n\ndata: {"type":"token","text":"ok"}\n\n');
    const events = [];
    for await (const event of readEvents(body)) events.push(event);
    expect(events).toEqual([{ type: "token", text: "ok" }]);
  });
});

const source = (id: string, section: string): Source => ({
  id,
  document: "doc",
  drug: "Lipitor",
  section,
  page: 4,
  text: "",
  anchor: "",
});

describe("withSources", () => {
  it("lists the cited sources in citation order", () => {
    expect(
      withSources(
        "Dose [S2] and [S1].",
        ["S2", "S1"],
        [source("S1", "6 Adverse"), source("S2", "2.2 Dosage")],
      ),
    ).toBe(
      "Dose [S2] and [S1].\n\nSources:\n[S2] Lipitor, section 2.2 Dosage, page 4\n[S1] Lipitor, section 6 Adverse, page 4",
    );
  });

  it("returns the answer alone without cited sources", () => {
    expect(withSources("Hello!", [], [])).toBe("Hello!");
  });
});

describe("sourceLabel", () => {
  it("names the source, its section and its page", () => {
    expect(sourceLabel(source("S2", "2.2 Dosage"))).toBe(
      "[S2] Lipitor, section 2.2 Dosage, page 4",
    );
  });
});

describe("endConversation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends a DELETE that outlives the page", () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response(null, { status: 204 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    endConversation("a b");

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/conversations/a%20b", {
      method: "DELETE",
      keepalive: true,
    });
  });

  it("ignores a failed request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.reject(new Error("offline"))),
    );

    expect(() => endConversation("id")).not.toThrow();
    await Promise.resolve();
  });
});
