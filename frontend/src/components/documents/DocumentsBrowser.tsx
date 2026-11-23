"use client";

import {
  Badge,
  Card,
  Drawer,
  Grid,
  LoadingSpinner,
  SearchInput,
  SkeletonCard,
  Tooltip,
} from "@geomak/ui";
import { Download } from "@geomak/ui/icons";
import { useEffect, useRef, useState } from "react";
import { LoadState } from "@/components/layout/LoadState";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { DocumentSummary } from "@/lib/contract/generated";
import {
  activeIngredients,
  documentTitle,
  downloadUrl,
  fetchDocuments,
  thumbnailUrl,
} from "@/lib/documents";
import { formatDate } from "@/lib/format";
import { DOCUMENT_TONES } from "@/lib/statusTones";
import { DocumentViewer } from "./DocumentViewer";
import styles from "./DocumentsBrowser.module.css";

export const SEARCH_DEBOUNCE_MS = 300;
export const PAGE_SIZE = 10;

// `attempt` changes on a retry, so the same page is requested again.
type Request = { q: string; page: number; attempt: number };
// All pages loaded so far for one search term.
type Loaded = { q: string; page: number; items: DocumentSummary[]; total: number };

// The app shell scrolls inside <main>; that element clips the observer's view, not the window.
function scrollParent(node: HTMLElement): HTMLElement | null {
  for (let parent = node.parentElement; parent; parent = parent.parentElement) {
    if (/auto|scroll/.test(getComputedStyle(parent).overflowY)) return parent;
  }
  return null;
}

function DownloadLink({ document, label }: { document: DocumentSummary; label: string }) {
  return (
    <Tooltip title="Download PDF">
      <a
        className={styles.download}
        href={downloadUrl(document.id)}
        download
        aria-label={`Download ${label}`}
      >
        <Download size={18} />
      </a>
    </Tooltip>
  );
}

function DocumentCard({
  document,
  onOpen,
}: {
  document: DocumentSummary;
  onOpen: (document: DocumentSummary) => void;
}) {
  const title = documentTitle(document);
  return (
    <Card className={styles.card}>
      <Card.Media>
        {/* The title button is the accessible control; this one only enlarges the click area. */}
        <button
          type="button"
          className={styles.media}
          onClick={() => onOpen(document)}
          tabIndex={-1}
          aria-hidden="true"
        >
          {/* A small PNG from the backend; the image optimizer adds nothing here. */}
          {/* oxlint-disable-next-line nextjs/no-img-element */}
          <img className={styles.thumbnail} src={thumbnailUrl(document.id)} alt="" loading="lazy" />
        </button>
      </Card.Media>
      <Card.Header
        title={
          <button type="button" className={styles.title} onClick={() => onOpen(document)}>
            {title}
          </button>
        }
        action={
          <Badge
            className={styles.pill}
            tone={DOCUMENT_TONES[document.status]}
            variant="solid"
            size="sm"
          >
            {document.status}
          </Badge>
        }
      />
      <Card.Body>
        <ul className={styles.ingredients} aria-label="Active ingredients">
          {activeIngredients(document.generic_name).map((name) => (
            <li key={name}>
              <Badge className={styles.ingredient} tone="info" variant="outline" size="sm">
                {name}
              </Badge>
            </li>
          ))}
        </ul>
        <p className={styles.meta}>
          {document.page_count === null ? "" : `${document.page_count} pages`}
          {document.ingested_at ? (
            <>
              {" · "}
              <span className={styles.ingested}>Ingested {formatDate(document.ingested_at)}</span>
            </>
          ) : null}
        </p>
      </Card.Body>
      <Card.Footer className={styles.footer}>
        <DownloadLink document={document} label={title} />
      </Card.Footer>
    </Card>
  );
}

export function DocumentsBrowser() {
  const [search, setSearch] = useState("");
  const [request, setRequest] = useState<Request>({ q: "", page: 1, attempt: 0 });
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  // A failure keeps its request, so a later request clears it.
  const [failed, setFailed] = useState<Request | null>(null);
  const [selected, setSelected] = useState<DocumentSummary | null>(null);
  const sentinel = useRef<HTMLDivElement>(null);

  // A new search term starts again at page 1.
  const q = useDebouncedValue(search.trim(), SEARCH_DEBOUNCE_MS);
  if (request.q !== q) setRequest({ q, page: 1, attempt: 0 });

  useEffect(() => {
    const controller = new AbortController();
    fetchDocuments(
      { q: request.q, page: request.page, pageSize: PAGE_SIZE },
      controller.signal,
    ).then(
      ({ items, total }) =>
        setLoaded((previous) => {
          if (request.page === 1 || previous?.q !== request.q) {
            return { q: request.q, page: request.page, items, total };
          }
          // Offset paging can repeat a row when rows are added between two pages.
          const seen = new Set(previous.items.map((item) => item.id));
          const added = items.filter((item) => !seen.has(item.id));
          return { q: request.q, page: request.page, items: [...previous.items, ...added], total };
        }),
      () => {
        if (!controller.signal.aborted) setFailed(request);
      },
    );
    return () => controller.abort();
  }, [request]);

  const current = loaded?.q === request.q ? loaded : null;
  const error =
    failed !== null &&
    failed.q === request.q &&
    failed.page === request.page &&
    failed.attempt === request.attempt;
  const loading = current?.page !== request.page && !error;
  const loadedPage = current?.page ?? 0;
  const hasMore = current !== null && current.items.length < current.total;

  // Load the next page when the end of the list comes into view.
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore || loading || error) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setRequest((now) => (now.page === loadedPage ? { ...now, page: loadedPage + 1 } : now));
      },
      { root: scrollParent(node), rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, loading, error, loadedPage]);

  return (
    <div className={styles.browser}>
      <div className={styles.toolbar}>
        <SearchInput
          className={styles.search}
          value={search}
          onChange={({ target }) => setSearch(target.value)}
          placeholder="Search by brand or generic name"
          label="Search documents"
          htmlFor="document-search"
        />
        {current ? (
          <p className={styles.count} aria-live="polite">
            Showing {current.items.length} of {current.total}
          </p>
        ) : null}
      </div>
      <Grid cols="repeat(auto-fill, minmax(220px, 1fr))" gap="md" aria-busy={loading}>
        {current?.items.map((document) => (
          <DocumentCard key={document.id} document={document} onOpen={setSelected} />
        ))}
        {loading && !current
          ? Array.from({ length: PAGE_SIZE }, (_, index) => (
              <SkeletonCard key={index} hasAvatar={false} lines={2} />
            ))
          : null}
      </Grid>
      {loading && current ? <LoadingSpinner inline size="sm" /> : null}
      {error ? (
        <LoadState
          error
          label="documents"
          onRetry={() => setRequest((now) => ({ ...now, attempt: now.attempt + 1 }))}
        />
      ) : null}
      {current?.total === 0 ? <p className={styles.empty}>No documents match the search.</p> : null}
      <div ref={sentinel} aria-hidden="true" />
      <Drawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        placement="right"
        size="xl"
        hasFooter={false}
        title={selected ? documentTitle(selected) : ""}
      >
        {selected ? (
          <DocumentViewer documentId={selected.id} title={documentTitle(selected)} />
        ) : null}
      </Drawer>
    </div>
  );
}
