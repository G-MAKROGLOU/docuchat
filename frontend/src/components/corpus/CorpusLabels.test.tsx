import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CorpusLabels } from "./CorpusLabels";

const SET_ID = "a60cc18b-0631-4cf0-b021-9f52224ece65";
const ENTRY = {
  set_id: SET_ID,
  title: "LIPITOR (ATORVASTATIN CALCIUM) TABLET [VIATRIS SPECIALTY LLC]",
  status: "queued",
  failure_reason: null,
  created_at: "2026-11-21T10:00:00Z",
};
const CATALOG = {
  set_id: SET_ID,
  title: "LIPITOR (ATORVASTATIN CALCIUM) TABLET [VIATRIS SPECIALTY LLC]",
  version: 8,
  published: "Jul 15, 2026",
};

const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

async function flush() {
  await act(async () => {
    await vi.runOnlyPendingTimersAsync();
  });
}

async function type(text: string) {
  const input = screen.getByLabelText("Drug name or set ID");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: text } });
  await flush();
}

// One key press, then 100 ms: shorter than the debounce.
async function keystroke(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(100);
  });
}

function queueBody(items: unknown[], total: number) {
  return Response.json({
    items,
    total,
    queued_total: total,
    added_total: 0,
    failed_total: 0,
    labels_per_pass: 50,
  });
}

describe("CorpusLabels", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows the queue with the counts", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({
        items: [ENTRY],
        total: 1,
        queued_total: 1,
        added_total: 0,
        failed_total: 0,
        labels_per_pass: 50,
      }),
    );

    render(<CorpusLabels />);
    await flush();

    expect(screen.getByText("Lipitor")).toBeTruthy();
    expect(screen.getByText("atorvastatin calcium")).toBeTruthy();
    expect(screen.getByText("Tablet \u00b7 Viatris Specialty LLC")).toBeTruthy();
    expect(screen.getByText(/1 queued, 0 added, 0 failed/)).toBeTruthy();
  });

  it("searches DailyMed by name and adds a result to the queue", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({
        items: [],
        total: 0,
        queued_total: 0,
        added_total: 0,
        failed_total: 0,
        labels_per_pass: 50,
      }),
    );
    fetchMock.mockResolvedValueOnce(Response.json([CATALOG]));
    fetchMock.mockResolvedValueOnce(Response.json(CATALOG, { status: 201 }));
    fetchMock.mockResolvedValueOnce(
      Response.json({
        items: [ENTRY],
        total: 1,
        queued_total: 1,
        added_total: 0,
        failed_total: 0,
        labels_per_pass: 50,
      }),
    );

    render(<CorpusLabels />);
    await flush();
    await type("lipitor");
    fireEvent.click(screen.getByRole("button", { name: /Lipitor/ }));
    await flush();

    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/labels/search?q=lipitor");
    expect(fetchMock.mock.calls[2]?.[1]?.method).toBe("POST");
    expect(screen.getByText("Added to the queue.")).toBeTruthy();
    // The added label is no longer offered.
    expect(screen.queryByRole("list", { name: "DailyMed results" })).toBeNull();
    expect(screen.getByLabelText("Label queue")).toBeTruthy();
  });

  it("checks a set ID directly and reports an unknown one", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({
        items: [],
        total: 0,
        queued_total: 0,
        added_total: 0,
        failed_total: 0,
        labels_per_pass: 50,
      }),
    );
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "x" }, { status: 404 }));

    render(<CorpusLabels />);
    await flush();
    await type(SET_ID);
    fireEvent.click(screen.getByRole("button", { name: /Set ID a60cc18b/ }));
    await flush();

    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/labels");
    expect(screen.getByText("DailyMed does not know this set ID.")).toBeTruthy();
  });

  it("searches once after the user pauses, and not for one character", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({
        items: [],
        total: 0,
        queued_total: 0,
        added_total: 0,
        failed_total: 0,
        labels_per_pass: 50,
      }),
    );
    fetchMock.mockResolvedValueOnce(Response.json([CATALOG]));

    render(<CorpusLabels />);
    await flush();
    const input = screen.getByLabelText("Drug name or set ID");
    fireEvent.focus(input);
    await keystroke(input, "l");
    await keystroke(input, "li");
    await keystroke(input, "lip");
    await keystroke(input, "lipi");
    await flush();

    const searches = fetchMock.mock.calls.filter(([url]) => url.includes("/labels/search"));
    expect(searches).toHaveLength(1);
    expect(searches[0]?.[0]).toBe("/api/v1/labels/search?q=lipi");
  });

  it("pages the queue and removes an entry with the delete icon", async () => {
    const entries = Array.from({ length: 10 }, (_, i) => ({ ...ENTRY, set_id: `set-${i}` }));
    fetchMock.mockResolvedValueOnce(queueBody(entries, 11));
    fetchMock.mockResolvedValueOnce(queueBody([{ ...ENTRY, set_id: "set-10" }], 11));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    fetchMock.mockResolvedValueOnce(queueBody(entries, 10));

    render(<CorpusLabels />);
    await flush();
    expect(screen.getByText("Page 1 of 2")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await flush();
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/labels?page=2&page_size=10");
    expect(screen.getByText("Page 2 of 2")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Remove Lipitor from the queue" }));
    await flush();

    expect(fetchMock.mock.calls[2]?.[1]?.method).toBe("DELETE");
    // The last page is empty now: the page goes back to the first, with one request.
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[3]?.[0]).toBe("/api/v1/labels?page=1&page_size=10");
    expect(screen.queryByRole("navigation", { name: "Queue pages" })).toBeNull();
    expect(document.activeElement?.textContent).toBe("Queue");
  });

  it("loads the first page once after an add from a later page", async () => {
    const entries = Array.from({ length: 10 }, (_, i) => ({ ...ENTRY, set_id: `set-${i}` }));
    fetchMock.mockResolvedValueOnce(queueBody(entries, 11));
    fetchMock.mockResolvedValueOnce(queueBody([{ ...ENTRY, set_id: "set-10" }], 11));
    fetchMock.mockResolvedValueOnce(Response.json(CATALOG, { status: 201 }));
    fetchMock.mockResolvedValueOnce(queueBody(entries, 12));

    render(<CorpusLabels />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await flush();
    await type(SET_ID);
    fireEvent.click(screen.getByRole("button", { name: /Set ID a60cc18b/ }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[3]?.[0]).toBe("/api/v1/labels?page=1&page_size=10");
    expect(screen.getByText("Page 1 of 2")).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText("Drug name or set ID"));
  });

  it("says the label is added when only the refresh of the queue fails", async () => {
    fetchMock.mockResolvedValueOnce(queueBody([], 0));
    fetchMock.mockResolvedValueOnce(Response.json(CATALOG, { status: 201 }));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));

    render(<CorpusLabels />);
    await flush();
    await type(SET_ID);
    fireEvent.click(screen.getByRole("button", { name: /Set ID a60cc18b/ }));
    await flush();

    expect(screen.getByText("Added to the queue.")).toBeTruthy();
    expect(screen.getByText("The queue could not be refreshed.", { exact: false })).toBeTruthy();
    expect(screen.queryByText("The label could not be added.")).toBeNull();
  });

  it("keeps the queue and the search text when a page change fails", async () => {
    const entries = Array.from({ length: 10 }, (_, i) => ({ ...ENTRY, set_id: `set-${i}` }));
    fetchMock.mockResolvedValueOnce(queueBody(entries, 11));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));

    render(<CorpusLabels />);
    await flush();
    fireEvent.change(screen.getByLabelText("Drug name or set ID"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await flush();

    expect(screen.getByText("The queue could not be refreshed.", { exact: false })).toBeTruthy();
    expect(screen.getByLabelText("Label queue")).toBeTruthy();
    expect((screen.getByLabelText("Drug name or set ID") as HTMLInputElement).value).toBe("x");
  });
});
