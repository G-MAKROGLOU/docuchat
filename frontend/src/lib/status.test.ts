import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentSummary } from "@/lib/contract/generated";
import {
  fetchAllDocuments,
  ingestedPerDay,
  largestByPages,
  PAGE_FAN_OUT,
  summarize,
} from "./status";

const base: DocumentSummary = {
  id: "a",
  brand_name: "A",
  generic_name: "a",
  page_count: 10,
  status: "ingested",
  ingested_at: "2026-11-01T10:00:00Z",
  failure_reason: null,
};

describe("summarize", () => {
  it("counts by status, sums pages and finds the latest ingestion", () => {
    const result = summarize([
      base,
      { ...base, id: "b", ingested_at: "2026-11-03T10:00:00Z", page_count: null },
      { ...base, id: "c", status: "failed", page_count: 5, ingested_at: null },
      { ...base, id: "d", status: "stored", page_count: null, ingested_at: null },
    ]);
    expect(result.total).toBe(4);
    expect(result.counts).toEqual({ stored: 1, ingesting: 0, ingested: 2, failed: 1 });
    expect(result.pages).toBe(15);
    expect(result.lastIngestedAt).toBe("2026-11-03T10:00:00Z");
    expect(result.attention.map((d) => d.id)).toEqual(["c", "d"]);
  });

  it("handles an empty list", () => {
    const result = summarize([]);
    expect(result.total).toBe(0);
    expect(result.lastIngestedAt).toBeNull();
    expect(result.attention).toEqual([]);
  });
});

describe("largestByPages", () => {
  it("sorts by page count, drops documents without pages and applies the limit", () => {
    const result = largestByPages(
      [
        { ...base, id: "a", page_count: 10 },
        { ...base, id: "b", page_count: 50 },
        { ...base, id: "c", page_count: null },
        { ...base, id: "d", page_count: 30 },
      ],
      2,
    );
    expect(result.map((d) => d.id)).toEqual(["b", "d"]);
  });
});

describe("fetchAllDocuments", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads every page with at most PAGE_FAN_OUT requests at the same time", async () => {
    let active = 0;
    let most = 0;
    const pages: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn<(url: string) => Promise<Response>>(async (url) => {
        const page = Number(new URL(url, "http://x").searchParams.get("page"));
        pages.push(String(page));
        active += 1;
        most = Math.max(most, active);
        await new Promise((resolve) => setTimeout(resolve, 1));
        active -= 1;
        return Response.json({
          items: [{ ...base, id: `p${page}` }],
          total: 950,
          page,
          page_size: 100,
        });
      }),
    );

    const documents = await fetchAllDocuments();

    expect(pages).toHaveLength(10);
    expect(most).toBe(PAGE_FAN_OUT);
    expect(documents.map((d) => d.id)).toEqual(Array.from({ length: 10 }, (_, i) => `p${i + 1}`));
  });
});

describe("ingestedPerDay", () => {
  it("counts by UTC day, oldest first, and keeps the latest days", () => {
    const result = ingestedPerDay(
      [
        { ...base, id: "a", ingested_at: "2026-11-02T23:00:00Z" },
        { ...base, id: "b", ingested_at: "2026-11-01T10:00:00Z" },
        { ...base, id: "c", ingested_at: "2026-11-02T01:00:00Z" },
        { ...base, id: "d", ingested_at: null },
      ],
      2,
    );
    expect(result).toEqual([
      { day: "2026-11-01", count: 1 },
      { day: "2026-11-02", count: 2 },
    ]);
  });
});
