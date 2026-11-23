"use client";

import { Button, Chat, type ChatMessage } from "@geomak/ui";
import { X } from "@geomak/ui/icons";
import { memo, useCallback, useMemo, useSyncExternalStore } from "react";
import { sourceLabel } from "@/lib/chat";
import type { Source } from "@/lib/contract/generated";
import { DocumentViewer } from "@/components/documents/DocumentViewer";
import styles from "./ChatPanel.module.css";
import { useChatSession } from "@/hooks/chat/useChatSession";
import { BOT_ID, BOT_NAME, USER_ID } from "./ChatProvider";
import { renderMarkdown } from "./Markdown";
import { PanelResizer } from "./PanelResizer";

const noSubscription = () => () => undefined;
const NO_SOURCES: Source[] = [];
const NO_FOLLOW_UPS: string[] = [];

// Memoized, so a streamed token parses only the message that changed, not the whole history.
const MessageBody = memo(function MessageBody({
  text,
  sources,
  followUps,
  onCite,
  onAsk,
}: {
  text: string;
  sources: Source[];
  followUps: string[];
  onCite: (source: Source) => void;
  onAsk: (question: string) => void;
}) {
  const body = useMemo(() => {
    const citations = Object.fromEntries(
      sources.map((source) => [source.id, () => onCite(source)]),
    );
    return renderMarkdown(text, citations);
  }, [text, sources, onCite]);
  return (
    <>
      {body}
      {followUps.length ? (
        <fieldset className={styles.suggestions} aria-label="Suggested questions">
          {followUps.map((question) => (
            <button
              key={question}
              type="button"
              className={styles.suggestion}
              onClick={() => onAsk(question)}
            >
              {question}
            </button>
          ))}
        </fieldset>
      ) : null}
    </>
  );
});

export function ChatPanel() {
  const {
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
  } = useChatSession();
  // Messages render in the browser only, so the server (UTC) and the browser show the same times.
  const inBrowser = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
  const ask = useCallback((question: string) => void send(question), [send]);

  // Chat types `text` as a string but renders it as a React child, so bot Markdown fits there.
  const lastId = messages.at(-1)?.id;
  const shown = messages.map((m): ChatMessage => {
    if (m.authorId !== BOT_ID) return m;
    const { id, authorId, authorName, avatar, timestamp } = m;
    const followUps =
      id === lastId && !busy ? (suggestionsById[id] ?? NO_FOLLOW_UPS) : NO_FOLLOW_UPS;
    const body = (
      <MessageBody
        text={m.text}
        sources={sourcesById[id] ?? NO_SOURCES}
        followUps={followUps}
        onCite={setCited}
        onAsk={ask}
      />
    );
    return { id, authorId, authorName, avatar, timestamp, text: body as unknown as string };
  });

  return (
    <div className={styles.layout}>
      <div className={styles.chat}>
        {busy ? (
          <Button
            className={styles.stop}
            content="Stop"
            variant="ghost"
            size="sm"
            aria-label="Stop the answer"
            onClick={stop}
          />
        ) : null}
        <Chat
          messages={inBrowser ? shown : []}
          currentUserId={USER_ID}
          onSend={ask}
          typingNames={waiting ? [BOT_NAME] : []}
          disabled={busy}
          placeholder="Ask a question about one or more medicines"
          emptyState={false}
          height="100%"
        />
      </div>
      {cited ? (
        <PanelResizer
          percent={sourcePercent}
          onChange={setSourcePercent}
          label="Resize the source panel"
        />
      ) : null}
      {cited ? (
        <aside
          className={styles.source}
          style={{ flexBasis: `${sourcePercent}%` }}
          aria-label="Cited source"
        >
          <header className={styles.header}>
            <span>{sourceLabel(cited)}</span>
            <Button
              variant="ghost"
              size="sm"
              icon={<X size={16} />}
              aria-label="Close the source"
              onClick={() => setCited(null)}
            />
          </header>
          <div className={styles.viewer}>
            <DocumentViewer
              key={cited.document}
              documentId={cited.document}
              page={cited.page}
              passage={cited.text}
              anchor={cited.anchor}
            />
          </div>
        </aside>
      ) : null}
    </div>
  );
}
