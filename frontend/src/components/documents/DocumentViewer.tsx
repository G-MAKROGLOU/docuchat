"use client";

import { PdfViewer } from "@geomak/ui";
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import styles from "./DocumentViewer.module.css";

// With a title, the URL ends in "<title>.pdf": the viewer saves a download under the last segment.
export function documentFileUrl(documentId: string, title?: string): string {
  const url = `${API_BASE}/documents/${encodeURIComponent(documentId)}/file`;
  // The viewer does not decode the segment, so only characters that break a URL path are replaced.
  const name = title?.replace(/[\\/?#%]/g, "-").trim();
  return name ? `${url}/${name}.pdf` : url;
}

// The first words of a cited chunk, found on its page, mark the cited passage.
export function highlightTarget(
  page?: number,
  anchor?: string,
): { page: number; phrase: string } | null {
  const phrase = anchor?.trim();
  return page && phrase ? { page, phrase } : null;
}

const PASSAGE_WORDS = 60;

// The phrases to try, longest first: the start of the cited passage, then its anchor. A long
// phrase can miss on the page (a table, a column break), so the anchor is the fallback.
export function highlightPhrases(passage?: string, anchor?: string): string[] {
  const words = passage?.split(/\s+/).filter(Boolean) ?? [];
  const short = anchor?.trim() ?? "";
  const long = words.slice(0, PASSAGE_WORDS).join(" ");
  return [long, short].filter((phrase, index, all) => phrase && all.indexOf(phrase) === index);
}

export function DocumentViewer({
  documentId,
  page,
  title,
  passage,
  anchor,
}: {
  documentId: string;
  page?: number;
  title?: string;
  passage?: string;
  anchor?: string;
}) {
  // PdfViewer ignores a `page` given before load, so pass it from the task after load.
  // Later changes of `page` then scroll the open document.
  const [loaded, setLoaded] = useState(false);
  const loadTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(loadTimer.current), []);
  // The phrase that was not found, for the passage it belongs to; the next shorter one is used.
  const phrases = highlightPhrases(passage, anchor);
  const target = phrases.join("\n");
  const [missed, setMissed] = useState<{ target: string; phrase: string } | null>(null);
  const skipped = missed?.target === target ? missed.phrase : null;
  const phrase = phrases.find((candidate) => candidate !== skipped);
  return (
    <div className={styles.viewer}>
      <PdfViewer
        source={documentFileUrl(documentId, title)}
        height="100%"
        page={loaded ? page : undefined}
        highlight={loaded ? highlightTarget(page, phrase) : null}
        onHighlightResolved={({ found }) => {
          if (!found && phrase) setMissed({ target, phrase });
        }}
        onLoad={() => {
          loadTimer.current = setTimeout(() => setLoaded(true), 0);
        }}
      />
    </div>
  );
}
