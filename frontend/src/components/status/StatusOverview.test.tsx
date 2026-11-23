import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentSummary, StatusResponse } from "@/lib/contract/generated";
import { chunksHelp } from "./StatusDashboard";
import { POLL_MS, StatusOverview } from "./StatusOverview";

const DOC: DocumentSummary = {
  id: "id-1",
  brand_name: "Alpha",
  generic_name: "alphacillin",
  page_count: 12,
  status: "ingested",
  ingested_at: "2026-11-01T10:00:00Z",
  failure_reason: null,
};
const FAILED: DocumentSummary = {
  ...DOC,
  id: "id-2",
  brand_name: "Beta",
  status: "failed",
  failure_reason: "ValueError: no body",
};

const SETTINGS = {
  chunk_tokens: 300,
  overlap_tokens: 30,
  top_k: 20,
  embedding_model: "m/embed",
  chat_model: "a/chat",
  rewrite_model: "a/rewrite",
  grade_model: "a/grade",
  generate_model: "a/generate",
  reasoning_effort: "low",
  grader_mode: "llm",
};

const IDLE: StatusResponse = {
  document_counts: { stored: 0, ingesting: 0, ingested: 1, failed: 1 },
  chunk_count: 30,
  token_count: 9000,
  embedding_models: ["m1"],
  ingestion_running: false,
  ingestion_phase: "idle",
  next_run_at: null,
};
const RUNNING: StatusResponse = { ...IDLE, ingestion_running: true, ingestion_phase: "ingesting" };

const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

// Answers by URL. Each /status call takes the next answer; the last one repeats.
function backend({
  documents = [DOC],
  status = [IDLE],
}: {
  documents?: DocumentSummary[];
  status?: (StatusResponse | Promise<Response>)[];
}) {
  const answers = [...status];
  fetchMock.mockImplementation(async (url) => {
    if (url.startsWith("/api/v1/documents")) {
      return Response.json({ items: documents, total: documents.length, page: 1, page_size: 100 });
    }
    if (url === "/api/v1/status") {
      const next = answers.length > 1 ? answers.shift() : answers[0];
      return next instanceof Promise ? next : Response.json(next);
    }
    if (url === "/api/v1/settings") return Response.json(SETTINGS);
    if (url === "/api/v1/ingestion") return Response.json({ running: true }, { status: 202 });
    throw new Error(`unexpected ${url}`);
  });
}

function calls(prefix: string) {
  return fetchMock.mock.calls.filter(([url]) => url.startsWith(prefix)).length;
}

async function flush() {
  await act(async () => {
    await vi.runOnlyPendingTimersAsync();
  });
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("StatusOverview", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows counts and lists documents that are not ingested", async () => {
    backend({ documents: [DOC, FAILED] });
    render(<StatusOverview />);
    await flush();

    expect(screen.getByText("Chunks").parentElement?.textContent).toContain("30");
    expect(screen.getByText("Embedding tokens").parentElement?.textContent).toContain("9,000");
    const list = screen.getByRole("list", { name: "Documents that are not ingested" });
    expect(list.textContent).toContain("Beta");
    expect(list.textContent).toContain("ValueError: no body");
    expect(list.textContent).not.toContain("Alpha");
    expect(screen.getByText("Last 14 days with activity")).toBeTruthy();
  });

  it("takes the counts from /status, so they follow a pass without the document list", async () => {
    const midPass: StatusResponse = {
      ...RUNNING,
      document_counts: { stored: 0, ingesting: 2, ingested: 40, failed: 0 },
    };
    backend({ documents: [DOC], status: [midPass] });
    render(<StatusOverview />);
    await flush();

    expect(screen.getByText("Documents").parentElement?.textContent).toContain("42");
    expect(screen.getByText("2 not ingested")).toBeTruthy();
    expect(calls("/api/v1/documents")).toBe(1);
  });

  it("starts an ingestion pass from the button", async () => {
    backend({ status: [IDLE, RUNNING] });
    render(<StatusOverview />);
    await flush();

    await act(async () => {
      screen.getByRole("button", { name: "Run ingestion now" }).click();
    });
    await wait(0);

    expect(calls("/api/v1/ingestion")).toBe(1);
    expect(screen.getByRole("button", { name: /Ingestion running/ })).toBeTruthy();
  });

  it("shows an error with a retry", async () => {
    fetchMock.mockRejectedValue(new Error("down"));
    render(<StatusOverview />);
    await flush();
    expect(screen.getByText("The status could not be loaded.", { exact: false })).toBeTruthy();

    backend({});
    await act(async () => {
      screen.getByRole("button", { name: "Try again" }).click();
    });
    await flush();
    expect(screen.getByText("Chunks")).toBeTruthy();
  });

  it("polls /status one request at a time and loads the documents again once at the end", async () => {
    const { promise: slow, resolve: finish } = Promise.withResolvers<Response>();
    backend({ status: [RUNNING, slow, IDLE] });
    render(<StatusOverview />);
    await wait(0);
    expect(calls("/api/v1/status")).toBe(1);
    expect(calls("/api/v1/documents")).toBe(1);

    // The second poll does not answer: no new request starts while it is in flight.
    await wait(POLL_MS);
    expect(calls("/api/v1/status")).toBe(2);
    await wait(POLL_MS * 5);
    expect(calls("/api/v1/status")).toBe(2);
    expect(calls("/api/v1/documents")).toBe(1);

    // The pass ends: one more document load, and the polling stops.
    await act(async () => {
      finish(Response.json(IDLE));
    });
    await wait(0);
    expect(calls("/api/v1/documents")).toBe(2);
    await wait(POLL_MS * 5);
    expect(calls("/api/v1/status")).toBe(2);
    expect(calls("/api/v1/documents")).toBe(2);
  });

  it("keeps the last values and says so when a poll fails", async () => {
    backend({ status: [RUNNING] });
    render(<StatusOverview />);
    await wait(0);

    fetchMock.mockImplementation(async () => {
      throw new Error("down");
    });
    await wait(POLL_MS);

    expect(screen.getByText(/The status could not be refreshed/)).toBeTruthy();
    expect(screen.getByText("Chunks")).toBeTruthy();
  });

  it("writes the current chunk size and overlap in the chunk help", () => {
    const help = chunksHelp(300, 30);

    expect(help).toContain("about 300 tokens, with 30 tokens of overlap");
  });
});
