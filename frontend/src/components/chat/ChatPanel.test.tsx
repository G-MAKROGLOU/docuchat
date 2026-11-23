import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { ChatProvider } from "./ChatProvider";

const PLACEHOLDER = "Ask a question about one or more medicines";
const GREETING = "Hello, how can I help you today?";
const LIPITOR_SOURCE = {
  id: "S1",
  document: "d",
  drug: "Lipitor",
  section: "2.2 Dosage",
  page: 4,
  text: "",
};

function sse(...events: object[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}

function renderChat() {
  return render(
    <ChatProvider>
      <ChatPanel />
    </ChatProvider>,
  );
}

function sendQuestion(text: string) {
  const input = screen.getByPlaceholderText(PLACEHOLDER);
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("ChatPanel", () => {
  it("keeps the chat when the page unmounts and comes back", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
        .mockResolvedValueOnce(sse({ type: "final", answer: "Hello!", citations: [] })),
    );
    const { rerender } = renderChat();
    await screen.findByText(GREETING);
    sendQuestion("hi");
    await screen.findByText("Hello!");

    rerender(<ChatProvider>{null}</ChatProvider>);
    expect(screen.queryByText("Hello!")).toBeNull();
    rerender(
      <ChatProvider>
        <ChatPanel />
      </ChatProvider>,
    );

    expect(await screen.findByText("Hello!")).toBeTruthy();
    expect(screen.getByText("hi")).toBeTruthy();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts with the greeting from the bot", async () => {
    renderChat();
    expect(await screen.findByText(GREETING)).toBeTruthy();
  });

  it("streams the answer with its sources after the question", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
      .mockResolvedValueOnce(
        sse(
          { type: "status", stage: "rewrite", message: "Reading the question" },
          {
            type: "sources",
            items: [LIPITOR_SOURCE],
          },
          { type: "token", text: "10 mg " },
          { type: "token", text: "[S1]." },
          { type: "final", answer: "10 mg [S1].", citations: ["S1"] },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    renderChat();
    await screen.findByText(GREETING);

    sendQuestion("What is the dose of Lipitor?");

    expect(screen.getByText("What is the dose of Lipitor?")).toBeTruthy();
    expect(await screen.findByText("Lipitor, section 2.2 Dosage, page 4")).toBeTruthy();
    expect(screen.getByText("Sources:")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Open source S1" })).toHaveLength(2);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/conversations/c1/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text: "What is the dose of Lipitor?" }),
      }),
    );
  });

  it("opens a cited source next to the chat and closes it", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
        .mockResolvedValueOnce(
          sse(
            { type: "sources", items: [LIPITOR_SOURCE] },
            { type: "final", answer: "10 mg [S1].", citations: ["S1"] },
          ),
        ),
    );
    renderChat();
    await screen.findByText(GREETING);
    sendQuestion("What is the dose of Lipitor?");

    const [citation] = await screen.findAllByRole("button", { name: "Open source S1" });
    expect(screen.queryByRole("complementary", { name: "Cited source" })).toBeNull();
    fireEvent.click(citation as HTMLElement);

    const panel = screen.getByRole("complementary", { name: "Cited source" });
    expect(panel.textContent).toContain("[S1] Lipitor, section 2.2 Dosage, page 4");
    fireEvent.click(screen.getByRole("button", { name: "Close the source" }));
    expect(screen.queryByRole("complementary", { name: "Cited source" })).toBeNull();
  });

  it("shows the refusal text", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
        .mockResolvedValueOnce(sse({ type: "refusal", reason: "out_of_scope" })),
    );
    renderChat();
    await screen.findByText(GREETING);

    sendQuestion("Tell me about aspirin");

    expect(
      await screen.findByText(
        "I can only answer questions about the medicines in my library of drug labels.",
      ),
    ).toBeTruthy();
  });

  it("keeps the streamed text and marks an answer that ends without a final event", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
        .mockResolvedValueOnce(sse({ type: "token", text: "Take 10 mg" })),
    );
    renderChat();
    await screen.findByText(GREETING);

    sendQuestion("dose?");

    expect(await screen.findByText("Take 10 mg")).toBeTruthy();
    expect(screen.getByText("The answer was cut off.")).toBeTruthy();
  });

  it("keeps the streamed text and shows a fixed text for an error event", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
        .mockResolvedValueOnce(
          sse(
            { type: "token", text: "Take 10 mg" },
            { type: "error", message: "Traceback: KeyError 'x'" },
          ),
        ),
    );
    renderChat();
    await screen.findByText(GREETING);

    sendQuestion("dose?");

    expect(await screen.findByText("The answer failed. Please try again.")).toBeTruthy();
    expect(screen.getByText("Take 10 mg")).toBeTruthy();
    expect(screen.queryByText(/Traceback/)).toBeNull();
  });

  it("stops a streaming answer and keeps what arrived", async () => {
    const encoder = new TextEncoder();
    let signal: AbortSignal | undefined;
    let stream: ReadableStreamDefaultController<Uint8Array> | undefined;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        stream = controller;
        controller.enqueue(encoder.encode('data: {"type":"token","text":"Part one"}\n\n'));
      },
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
        .mockImplementationOnce(async (_url, init) => {
          signal = init?.signal ?? undefined;
          // A real fetch body errors when its signal aborts.
          signal?.addEventListener("abort", () =>
            stream?.error(new DOMException("aborted", "AbortError")),
          );
          return new Response(body, { headers: { "content-type": "text/event-stream" } });
        }),
    );
    renderChat();
    await screen.findByText(GREETING);

    sendQuestion("dose?");
    expect(await screen.findByText("Part one")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop the answer" }));

    expect(await screen.findByText("The answer was stopped.")).toBeTruthy();
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByRole("button", { name: "Stop the answer" })).toBeNull();
  });

  it("shows follow-up questions under the latest answer and sends one on click", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ id: "c1" }, { status: 201 }))
      .mockResolvedValueOnce(
        sse(
          { type: "token", text: "Hello!" },
          { type: "final", answer: "Hello!", citations: [] },
          {
            type: "suggestions",
            items: ["What is the dose of Lipitor?", "Side effects of Lipitor?"],
          },
        ),
      )
      .mockResolvedValueOnce(sse({ type: "final", answer: "Sure.", citations: [] }));
    vi.stubGlobal("fetch", fetchMock);
    renderChat();
    await screen.findByText(GREETING);

    sendQuestion("hi");
    const chip = await screen.findByRole("button", { name: "Side effects of Lipitor?" });
    expect(screen.getByRole("group", { name: "Suggested questions" }).childElementCount).toBe(2);
    fireEvent.click(chip);

    expect(await screen.findByText("Sure.")).toBeTruthy();
    const [, init] = fetchMock.mock.calls[2] ?? [];
    expect(JSON.parse(String(init?.body))).toEqual({ text: "Side effects of Lipitor?" });
    // The chips belong to the earlier answer, so they are gone now.
    expect(screen.queryByRole("group", { name: "Suggested questions" })).toBeNull();
  });
});
