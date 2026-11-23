import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsForm } from "./SettingsForm";

const SETTINGS = {
  chunk_tokens: 500,
  overlap_tokens: 50,
  top_k: 20,
  chat_model: "a/chat",
  rewrite_model: "a/rewrite",
  grade_model: "a/grade",
  generate_model: "a/generate",
  reasoning_effort: "low",
  grader_mode: "llm",
  embedding_model: "m/embed",
};
const STATS = {
  chunk_count: 4500,
  token_count: 1000000,
  embedding_models: ["m/embed"],
  ingestion_running: false,
  ingestion_phase: "idle",
  next_run_at: null,
};

const OPTIONS = {
  chat_models: ["a/chat", "a/generate", "a/grade", "a/new", "a/rewrite"],
  embedding_models: ["m/embed", "x/other"],
};

const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

async function flush() {
  await act(async () => {
    await vi.runOnlyPendingTimersAsync();
  });
}

function loadPage() {
  fetchMock.mockResolvedValueOnce(Response.json(SETTINGS));
  fetchMock.mockResolvedValueOnce(Response.json(STATS));
  fetchMock.mockResolvedValueOnce(Response.json({ items: [], total: 50, page: 1, page_size: 1 }));
  fetchMock.mockResolvedValueOnce(Response.json(OPTIONS));
}

// Radix tabs open on mouse down.
async function openTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name: new RegExp(name) }), { button: 0 });
  await flush();
}

function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("SettingsForm", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("explains the effect of the chunk size and keeps Save off until a value changes", async () => {
    loadPage();

    render(<SettingsForm />);
    await flush();

    expect(screen.getByText(/Larger chunks: each label is cut into fewer chunks/)).toBeTruthy();
    expect(screen.getByText(/Smaller chunks: each label is cut into more chunks/)).toBeTruthy();
    const save = screen.getByRole("button", { name: "Save indexing" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    // One tab for each section.
    for (const name of ["Indexing", "Search", "Models", "Answer checking"]) {
      expect(screen.getByRole("tab", { name: new RegExp(name) })).toBeTruthy();
    }
  });

  it("saves a change without chunk fields at once", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, top_k: 30, reingest_started: false }),
    );

    render(<SettingsForm />);
    await flush();
    await openTab("Search");
    change("Chunks per search (top-k)", "30");
    fireEvent.click(screen.getByRole("button", { name: "Save search" }));
    await flush();

    const request = fetchMock.mock.calls[4];
    expect(request?.[1]?.method).toBe("PUT");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      top_k: 30,
      reingest_confirmed: false,
    });
    expect(screen.getByText("Saved.")).toBeTruthy();
  });

  it("asks for approval before a chunk change and saves it with the approval", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, chunk_tokens: 250, reingest_started: true }),
    );

    render(<SettingsForm />);
    await flush();
    change("Chunk size (tokens)", "250");
    fireEvent.click(screen.getByRole("button", { name: "Save indexing" }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(screen.getByText("Embed every document again?")).toBeTruthy();
    expect(screen.getByText(/so the index gets (fewer|more) chunks/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Embed again" }));
    await flush();

    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toMatchObject({
      chunk_tokens: 250,
      reingest_confirmed: true,
    });
    expect(screen.getByText(/Every document is embedded again now/)).toBeTruthy();
  });

  it("does not save when the approval is cancelled", async () => {
    loadPage();

    render(<SettingsForm />);
    await flush();
    change("Overlap (tokens)", "0");
    fireEvent.click(screen.getByRole("button", { name: "Save indexing" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("saves only the edits of its own tab, keeps the others and can discard them", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, top_k: 30, reingest_started: false }),
    );

    render(<SettingsForm />);
    await flush();
    change("Chunk size (tokens)", "250");
    await openTab("Search");
    change("Chunks per search (top-k)", "30");
    fireEvent.click(screen.getByRole("button", { name: "Save search" }));
    await flush();

    // The unsaved chunk size is not sent with the top-k change.
    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toMatchObject({
      chunk_tokens: 500,
      top_k: 30,
    });
    // The Chunking tab marks its unsaved edit and keeps it until it is discarded.
    expect(screen.getByRole("tab", { name: /Indexing/ }).textContent).toContain("•");
    await openTab("Indexing");
    expect((screen.getByLabelText("Chunk size (tokens)") as HTMLInputElement).value).toBe("250");
    fireEvent.click(screen.getByRole("button", { name: "Discard changes of indexing" }));
    await flush();
    expect((screen.getByLabelText("Chunk size (tokens)") as HTMLInputElement).value).toBe("500");
    expect(screen.getByRole("tab", { name: /Indexing/ }).textContent).not.toContain("•");
  });

  it("picks a model from a dropdown and saves it without an approval", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, generate_model: "a/new", reingest_started: false }),
    );

    render(<SettingsForm />);
    await flush();
    await openTab("Models");
    // Chat, Rewrite, Grade and Generate, in this order.
    fireEvent.click(screen.getAllByRole("combobox")[3] as HTMLElement);
    await flush();
    fireEvent.click(screen.getByRole("option", { name: "a/new" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Save models" }));
    await flush();

    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toMatchObject({
      generate_model: "a/new",
      reingest_confirmed: false,
    });
    expect(screen.getByText("Saved.")).toBeTruthy();
  });

  it("asks for approval before another embedding model, and warns that chat stops", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, embedding_model: "x/other", reingest_started: true }),
    );

    render(<SettingsForm />);
    await flush();
    fireEvent.click(screen.getByRole("combobox"));
    await flush();
    fireEvent.click(screen.getByRole("option", { name: "x/other" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Save indexing" }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(screen.getByText(/chat cannot answer any question until every document/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Embed again" }));
    await flush();

    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toMatchObject({
      embedding_model: "x/other",
      reingest_confirmed: true,
    });
  });

  it("offers only the current models when the model lists cannot be loaded", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(SETTINGS));
    fetchMock.mockResolvedValueOnce(Response.json(STATS));
    fetchMock.mockResolvedValueOnce(Response.json({ items: [], total: 50, page: 1, page_size: 1 }));
    fetchMock.mockRejectedValueOnce(new Error("down"));

    render(<SettingsForm />);
    await flush();
    await openTab("Models");

    expect(screen.getByText(/model list of OpenRouter could not be loaded/)).toBeTruthy();
  });

  it("asks for the approval when the API answers 409 without a running pass", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "Confirm it." }, { status: 409 }));
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, top_k: 30, reingest_started: false }),
    );

    render(<SettingsForm />);
    await flush();
    await openTab("Search");
    change("Chunks per search (top-k)", "30");
    fireEvent.click(screen.getByRole("button", { name: "Save search" }));
    await flush();

    expect(screen.getByText("Embed every document again?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Embed again" }));
    await flush();

    expect(JSON.parse(String(fetchMock.mock.calls[5]?.[1]?.body))).toMatchObject({
      top_k: 30,
      reingest_confirmed: true,
    });
    expect(screen.getByText(/The next ingestion pass embeds every document again/)).toBeTruthy();
  });

  it("opens the form without the corpus numbers when they cannot be loaded", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(SETTINGS));
    fetchMock.mockRejectedValueOnce(new Error("down"));
    fetchMock.mockRejectedValueOnce(new Error("down"));
    fetchMock.mockResolvedValueOnce(Response.json(OPTIONS));

    render(<SettingsForm />);
    await flush();
    change("Chunk size (tokens)", "250");
    fireEvent.click(screen.getByRole("button", { name: "Save indexing" }));
    await flush();

    expect(screen.getByText("Embed every document again?")).toBeTruthy();
    expect(screen.queryByText(/The index now has/)).toBeNull();
    expect(screen.getByText(/All documents are parsed and embedded again/)).toBeTruthy();
  });

  it("picks the grader from the tiles and saves it", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, grader_mode: "rule", reingest_started: false }),
    );

    render(<SettingsForm />);
    await flush();
    await openTab("Answer checking");
    fireEvent.click(screen.getByRole("radio", { name: /Rules/ }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Save answer checking" }));
    await flush();

    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toMatchObject({
      grader_mode: "rule",
    });
    expect(screen.getByText("Saved.")).toBeTruthy();
  });

  it("picks the reasoning effort from the tiles and saves it", async () => {
    loadPage();
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...SETTINGS, reasoning_effort: "high", reingest_started: false }),
    );

    render(<SettingsForm />);
    await flush();
    await openTab("Models");
    fireEvent.click(screen.getByRole("radio", { name: /High/ }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Save models" }));
    await flush();

    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toMatchObject({
      reasoning_effort: "high",
    });
    expect(screen.getByText("Saved.")).toBeTruthy();
  });
});
