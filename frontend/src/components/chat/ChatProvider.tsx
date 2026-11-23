"use client";

import type { ChatMessage } from "@geomak/ui";
import {
  type ReactNode,
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { APP_NAME, LOGO_SRC } from "@/lib/brand";
import type { Source } from "@/lib/contract/generated";
import { REFUSAL_TEXT, ask, endConversation, startConversation, withSources } from "@/lib/chat";

export const USER_ID = "user";
export const BOT_ID = "bot";
export const BOT_NAME = APP_NAME;
const BOT = { authorId: BOT_ID, authorName: BOT_NAME, avatar: LOGO_SRC };
const GREETING = "Hello, how can I help you today?";
const DEFAULT_SOURCE_PERCENT = 50;

// Tokens that arrive within this time update the message once.
const TOKEN_BATCH_MS = 50;

const FAILED_TEXT = "The answer failed. Please try again.";
const CUT_OFF_TEXT = "The answer was cut off.";
const STOPPED_TEXT = "The answer was stopped.";

function withNote(partial: string, note: string): string {
  return partial ? `${partial}\n\n${note}` : note;
}

export interface ChatSession {
  messages: ChatMessage[];
  /** The sources of each bot message, by message ID. */
  sourcesById: Record<string, Source[]>;
  /** Follow-up questions by bot message ID; only the latest message shows them. */
  suggestionsById: Record<string, string[]>;
  busy: boolean;
  /** True from the question until the first part of the reply arrives. */
  waiting: boolean;
  /** The source open next to the chat, and its width in percent. */
  cited: Source | null;
  setCited: (source: Source | null) => void;
  sourcePercent: number;
  setSourcePercent: (percent: number) => void;
  send: (text: string) => Promise<void>;
  /** Stops the answer that streams now. */
  stop: () => void;
}

export const ChatContext = createContext<ChatSession | null>(null);

/** Holds the chat above the pages, so it survives navigation; a reload starts a new chat. */
export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    { id: "greeting", ...BOT, text: GREETING, timestamp: new Date() },
  ]);
  const [sourcesById, setSourcesById] = useState<Record<string, Source[]>>({});
  const [suggestionsById, setSuggestionsById] = useState<Record<string, string[]>>({});
  const [cited, setCited] = useState<Source | null>(null);
  const [sourcePercent, setSourcePercent] = useState(DEFAULT_SOURCE_PERCENT);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  // One conversation per provider; two sends at once share the same start.
  const conversation = useRef<Promise<string> | null>(null);
  // The started ID, read synchronously when the page unloads.
  const conversationId = useRef<string | null>(null);
  const answer = useRef<AbortController | null>(null);
  // Local message IDs. crypto.randomUUID needs a secure context, which a LAN address is not.
  const lastId = useRef(0);

  // An answer stops when the provider unmounts.
  useEffect(() => () => answer.current?.abort(), []);

  // A reload or a closed tab ends the chat, so the server deletes it. A page kept in the
  // back-forward cache (persisted) can come back, so its chat stays.
  useEffect(() => {
    const onPageHide = (event: PageTransitionEvent) => {
      if (event.persisted || !conversationId.current) return;
      endConversation(conversationId.current);
      conversationId.current = null;
      conversation.current = null;
    };
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, []);

  // Uses only state setters and refs, so it never goes stale and can stay the same function.
  const send = useCallback(async (text: string) => {
    const nextId = (prefix: string) => {
      lastId.current += 1;
      return `${prefix}-${lastId.current}`;
    };
    const setBotText = (id: string, reply: string) => {
      setWaiting(false);
      setMessages((current) => {
        const exists = current.some((m) => m.id === id);
        return exists
          ? current.map((m) => (m.id === id ? { ...m, text: reply } : m))
          : [...current, { id, ...BOT, text: reply, timestamp: new Date() }];
      });
    };

    const userId = nextId("user");
    setMessages((current) => [
      ...current,
      { id: userId, authorId: USER_ID, text, timestamp: new Date() },
    ]);
    setBusy(true);
    setWaiting(true);
    const id = nextId("bot");
    const controller = new AbortController();
    answer.current = controller;
    let partial = "";
    let sources: Source[] = [];
    let finished = false;
    let pending: ReturnType<typeof setTimeout> | undefined;
    const settle = (reply: string) => {
      clearTimeout(pending);
      pending = undefined;
      setBotText(id, reply);
    };
    try {
      conversation.current ??= startConversation().catch((error: unknown) => {
        conversation.current = null;
        throw error;
      });
      const started = await conversation.current;
      conversationId.current = started;
      for await (const event of await ask(started, text, controller.signal)) {
        if (event.type === "token") {
          partial += event.text;
          pending ??= setTimeout(() => settle(partial), TOKEN_BATCH_MS);
        } else if (event.type === "sources") {
          sources = event.items;
          const { items } = event;
          setSourcesById((current) => ({ ...current, [id]: items }));
        } else if (event.type === "final") {
          finished = true;
          settle(withSources(event.answer, event.citations, sources));
        } else if (event.type === "suggestions") {
          const { items } = event;
          setSuggestionsById((current) => ({ ...current, [id]: items }));
        } else if (event.type === "refusal") {
          finished = true;
          settle(REFUSAL_TEXT[event.reason]);
        } else if (event.type === "error") {
          // The backend message can be technical, so the user sees a fixed text.
          finished = true;
          settle(withNote(partial, FAILED_TEXT));
        }
      }
      if (!finished) settle(withNote(partial, CUT_OFF_TEXT));
    } catch {
      if (!finished) {
        settle(withNote(partial, controller.signal.aborted ? STOPPED_TEXT : FAILED_TEXT));
      }
    } finally {
      clearTimeout(pending);
      if (answer.current === controller) answer.current = null;
      setBusy(false);
    }
  }, []);

  const stop = useCallback(() => answer.current?.abort(), []);

  const session = useMemo<ChatSession>(
    () => ({
      messages,
      sourcesById,
      suggestionsById,
      busy,
      waiting,
      cited,
      setCited,
      sourcePercent,
      setSourcePercent,
      send,
      stop,
    }),
    [messages, sourcesById, suggestionsById, busy, waiting, cited, sourcePercent, send, stop],
  );
  return <ChatContext value={session}>{children}</ChatContext>;
}
