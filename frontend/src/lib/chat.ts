import { API_BASE, postStream, sendJson } from "@/lib/api";
import type {
  ConversationCreated,
  RefusalEvent,
  Source,
  StreamEvent,
} from "@/lib/contract/generated";

// Same texts as the backend stores for a refusal (backend/app/application/chat_prompts.py).
export const REFUSAL_TEXT: Record<RefusalEvent["reason"], string> = {
  no_relevant_context:
    "I could not find this in the drug labels I have. Try to name the medicine or ask about a specific topic, such as dosage or side effects.",
  no_valid_citation:
    "I could not give an answer that the drug labels support. Please rephrase the question.",
  out_of_scope: "I can only answer questions about the medicines in my library of drug labels.",
  drug_not_in_corpus:
    "This medicine is not in my library of drug labels. Ask about one of the medicines in the library.",
};

export async function startConversation(): Promise<string> {
  const { status, body } = await sendJson("POST", "/conversations");
  if (status < 200 || status >= 300) throw new Error(`Could not start a conversation (${status})`);
  return (body as ConversationCreated).id;
}

/** Deletes the conversation on the server. keepalive lets the request finish after a page unload. */
export function endConversation(conversationId: string): void {
  const path = `${API_BASE}/conversations/${encodeURIComponent(conversationId)}`;
  fetch(path, { method: "DELETE", keepalive: true }).catch(() => undefined);
}

function parseEvent(json: string): StreamEvent | null {
  try {
    return JSON.parse(json) as StreamEvent;
  } catch {
    return null;
  }
}

/** Parses a server-sent event stream of `data: <json>` blocks. A malformed block is skipped. */
export async function* readEvents(
  body: ReadableStream<Uint8Array<ArrayBuffer>>,
): AsyncGenerator<StreamEvent> {
  let buffer = "";
  for await (const value of body.pipeThrough(new TextDecoderStream())) {
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of block.split("\n")) {
        const event = line.startsWith("data: ") ? parseEvent(line.slice(6)) : null;
        if (event) yield event;
      }
    }
  }
}

export async function ask(
  conversationId: string,
  text: string,
  signal: AbortSignal,
): Promise<AsyncGenerator<StreamEvent>> {
  const path = `/conversations/${encodeURIComponent(conversationId)}/messages`;
  const response = await postStream(path, { text }, signal);
  return readEvents(response.body as ReadableStream<Uint8Array<ArrayBuffer>>);
}

export function sourceLabel(s: Source): string {
  return `[${s.id}] ${s.drug}, section ${s.section}, page ${s.page}`;
}

/** The answer, then one line per cited source in citation order. */
export function withSources(answer: string, citations: string[], sources: Source[]): string {
  const byId = new Map(sources.map((s) => [s.id, s]));
  const lines = citations
    .map((id) => byId.get(id))
    .filter((s): s is Source => s !== undefined)
    .map(sourceLabel);
  return lines.length ? `${answer}\n\nSources:\n${lines.join("\n")}` : answer;
}
