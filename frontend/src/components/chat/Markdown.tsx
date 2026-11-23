import type { ReactNode } from "react";
import styles from "./Markdown.module.css";

// The Markdown subset the answers use: paragraphs, headings, nested "-"/"*"/"1." lists,
// **bold**, *italic*, `code` and [S1] citation buttons. Builds React elements only,
// so model text cannot inject HTML.
// Keys are positions: the output is rebuilt from the full text on every render.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[S\d+\])/g;
const ITEM = /^( *)([-*]|\d+\.) +(.*)$/;
const HEADING = /^#{1,6} +(.*)$/;
const CITATION = /^\[(S\d+)\]$/;

/** Citation ID ("S1") to the action of its marker. */
export type Citations = Record<string, () => void>;

function renderInline(text: string, citations: Citations = {}): ReactNode[] {
  const out: ReactNode[] = [];
  let key = 0;
  for (const part of text.split(INLINE)) {
    key += 1;
    const cited = CITATION.exec(part)?.[1];
    const open = cited === undefined ? undefined : citations[cited];
    if (open)
      out.push(
        <button
          key={key}
          type="button"
          className={styles.citation}
          aria-label={`Open source ${cited}`}
          onClick={open}
        >
          {part}
        </button>,
      );
    else if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      out.push(<strong key={key}>{part.slice(2, -2)}</strong>);
    else if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      out.push(<code key={key}>{part.slice(1, -1)}</code>);
    else if (part.startsWith("*") && part.endsWith("*") && part.length > 2)
      out.push(<em key={key}>{part.slice(1, -1)}</em>);
    else out.push(part);
  }
  return out;
}

interface Item {
  text: string;
  children: List | null;
}
interface List {
  ordered: boolean;
  items: Item[];
}

function renderList(list: List, key: number, citations: Citations): ReactNode {
  const items: ReactNode[] = [];
  for (const item of list.items) {
    items.push(
      <li key={items.length}>
        {renderInline(item.text, citations)}
        {item.children && renderList(item.children, 0, citations)}
      </li>,
    );
  }
  return list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
}

function renderParagraph(lines: string[], key: number, citations: Citations): ReactNode {
  const parts: ReactNode[] = [];
  for (const line of lines) {
    parts.push(
      <span key={parts.length}>
        {parts.length > 0 && <br />}
        {renderInline(line, citations)}
      </span>,
    );
  }
  return <p key={key}>{parts}</p>;
}

export function renderMarkdown(text: string, citations: Citations = {}): ReactNode {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  // Open lists by indent; the first entry is the top-level list.
  let stack: { indent: number; list: List }[] = [];

  const flushParagraph = () => {
    if (paragraph.length) blocks.push(renderParagraph(paragraph, blocks.length, citations));
    paragraph = [];
  };
  const flushList = () => {
    const first = stack[0];
    if (first) blocks.push(renderList(first.list, blocks.length, citations));
    stack = [];
  };

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = ITEM.exec(line);
    if (item) {
      flushParagraph();
      const [, spaces = "", marker = "-", content = ""] = item;
      const indent = spaces.length;
      const ordered = marker !== "-" && marker !== "*";
      // Keep the top-level list: a less indented item joins it instead of dropping it.
      while (stack.length > 1 && indent < (stack.at(-1)?.indent ?? -1)) stack.pop();
      let top = stack.at(-1);
      if (!top || indent > top.indent) {
        const list: List = { ordered, items: [] };
        const parent = top?.list.items.at(-1);
        if (parent) parent.children = list;
        else flushList();
        top = { indent, list };
        stack.push(top);
      }
      top.list.items.push({ text: content, children: null });
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    flushList();
    const heading = HEADING.exec(line);
    if (heading) {
      flushParagraph();
      blocks.push(
        <p key={blocks.length}>
          <strong>{renderInline(heading[1] ?? "", citations)}</strong>
        </p>,
      );
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  return <div className={styles.markdown}>{blocks}</div>;
}
