import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentListResponse, DocumentSummary } from "@/lib/contract/generated";
import { DocumentsBrowser, SEARCH_DEBOUNCE_MS } from "./DocumentsBrowser";

// The PDF viewer needs a canvas and a worker; jsdom has neither.
vi.mock("./DocumentViewer", () => ({
  DocumentViewer: ({ documentId, title }: { documentId: string; title?: string }) => (
    <p>
      viewer {documentId} {title}
    </p>
  ),
}));

const ALPHA: DocumentSummary = {
  id: "id-1",
  brand_name: "",
  generic_name: "alphacillin",
  page_count: 12,
  status: "ingested",
  ingested_at: "2026-11-01T10:00:00Z",
  failure_reason: null,
};
const BETA: DocumentSummary = { ...ALPHA, id: "id-2", brand_name: "Beta", generic_name: "betanol" };

function page(items: DocumentSummary[], total = items.length): DocumentListResponse {
  return { items, total, page: 1, page_size: 10 };
}

const fetchMock = vi.fn<(url: string) => Promise<Response>>();

// jsdom has no IntersectionObserver; the test fires the latest callback by hand.
let intersect: (() => void) | null = null;
class FakeObserver {
  constructor(private readonly callback: IntersectionObserverCallback) {}
  observe() {
    intersect = () =>
      this.callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      );
  }
  disconnect() {
    intersect = null;
  }
}

function respond(body: DocumentListResponse) {
  fetchMock.mockResolvedValueOnce(Response.json(body));
}

async function flush() {
  await act(async () => {
    await vi.runOnlyPendingTimersAsync();
  });
}

describe("DocumentsBrowser", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("IntersectionObserver", FakeObserver);
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("lists the documents with the generic name as title when the brand is empty", async () => {
    respond(page([ALPHA, BETA]));
    render(<DocumentsBrowser />);
    await flush();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documents?page=1&page_size=10",
      expect.anything(),
    );
    expect(screen.getByRole("button", { name: "alphacillin" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Beta" })).toBeTruthy();
    const download = screen.getByRole("link", { name: "Download Beta" });
    expect(download.getAttribute("href")).toBe("/api/v1/documents/id-2/file?download=1");
    expect(download.hasAttribute("download")).toBe(true);
    expect(document.querySelector('img[src="/api/v1/documents/id-1/thumbnail?v=2"]')).toBeTruthy();
  });

  it("searches on the server after the debounce, from page 1", async () => {
    respond(page([ALPHA, BETA]));
    render(<DocumentsBrowser />);
    await flush();

    respond(page([BETA]));
    fireEvent.change(screen.getByLabelText("Search documents"), { target: { value: "be" } });
    fireEvent.change(screen.getByLabelText("Search documents"), { target: { value: "bet" } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/documents?page=1&page_size=10&q=bet",
      expect.anything(),
    );
    expect(screen.queryByRole("button", { name: "alphacillin" })).toBeNull();
  });

  it("appends the next page when the end of the list comes into view", async () => {
    respond(page([ALPHA], 2));
    render(<DocumentsBrowser />);
    await flush();
    expect(screen.getByText("Showing 1 of 2")).toBeTruthy();

    respond(page([BETA], 2));
    act(() => intersect?.());
    await flush();

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/documents?page=2&page_size=10",
      expect.anything(),
    );
    expect(screen.getByRole("button", { name: "alphacillin" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Beta" })).toBeTruthy();
    expect(screen.getByText("Showing 2 of 2")).toBeTruthy();
    // All rows are loaded, so the observer stops.
    expect(intersect).toBeNull();
  });

  it("shows the active ingredients as pills", async () => {
    respond(page([{ ...BETA, generic_name: "sacubitril and valsartan" }]));
    render(<DocumentsBrowser />);
    await flush();

    const list = screen.getByRole("list", { name: "Active ingredients" });
    expect(list.textContent).toBe("sacubitrilvalsartan");
    expect(screen.getByText("Ingested Nov 1, 2026").parentElement?.textContent).toBe(
      "12 pages · Ingested Nov 1, 2026",
    );
  });

  it("shows a message when nothing matches", async () => {
    respond(page([]));
    render(<DocumentsBrowser />);
    await flush();

    expect(screen.getByText("No documents match the search.")).toBeTruthy();
  });

  it("shows an error when the list cannot load", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
    render(<DocumentsBrowser />);
    await flush();

    expect(screen.getByText("The documents could not be loaded.")).toBeTruthy();

    respond(page([BETA]));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("The documents could not be loaded.")).toBeNull();
    expect(screen.getByRole("button", { name: "Beta" })).toBeTruthy();
  });

  it("opens the preview drawer with the viewer only", async () => {
    respond(page([BETA]));
    render(<DocumentsBrowser />);
    await flush();

    fireEvent.click(screen.getByRole("button", { name: "Beta" }));
    await flush();

    const drawer = screen.getByRole("dialog");
    // The viewer toolbar has its own download, named by the title.
    expect(drawer.textContent).toContain("viewer id-2 Beta");
    expect(drawer.querySelector("a[download]")).toBeNull();
  });
});
