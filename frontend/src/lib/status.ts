import { getJson, sendJson } from "@/lib/api";
import type {
  DocumentStatus,
  DocumentSummary,
  SettingsResponse,
  StatusResponse,
} from "@/lib/contract/generated";
import { fetchDocuments, MAX_PAGE_SIZE } from "@/lib/documents";

export const STATUS_ORDER: DocumentStatus[] = ["ingested", "ingesting", "stored", "failed"];

// The number of days in the ingested-per-day chart.
export const PER_DAY_DAYS = 14;

// The most document pages requested at the same time.
export const PAGE_FAN_OUT = 4;

export type StatusSummary = {
  total: number;
  counts: Record<DocumentStatus, number>;
  pages: number;
  lastIngestedAt: string | null;
  // Documents that are not ingested: stored, ingesting or failed.
  attention: DocumentSummary[];
};

export function summarize(documents: DocumentSummary[]): StatusSummary {
  const counts: Record<DocumentStatus, number> = {
    stored: 0,
    ingesting: 0,
    ingested: 0,
    failed: 0,
  };
  let pages = 0;
  let last: string | null = null;
  for (const document of documents) {
    counts[document.status] += 1;
    pages += document.page_count ?? 0;
    if (document.ingested_at && (!last || new Date(document.ingested_at) > new Date(last))) {
      last = document.ingested_at;
    }
  }
  return {
    total: documents.length,
    counts,
    pages,
    lastIngestedAt: last,
    attention: documents.filter((document) => document.status !== "ingested"),
  };
}

// Runs `run` for each item with at most `limit` calls at the same time. Keeps the order.
// After a failure no new call starts.
async function mapLimited<T, R>(
  items: T[],
  limit: number,
  run: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = [];
  let next = 0;
  let failed = false;
  const worker = async (): Promise<void> => {
    const index = next;
    next += 1;
    if (failed || index >= items.length) return;
    try {
      results[index] = await run(items[index] as T);
    } catch (error) {
      failed = true;
      throw error;
    }
    return worker();
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

export async function fetchAllDocuments(signal?: AbortSignal): Promise<DocumentSummary[]> {
  const pageSize = MAX_PAGE_SIZE;
  const first = await fetchDocuments({ q: "", page: 1, pageSize }, signal);
  const pageCount = Math.ceil(first.total / pageSize);
  const pages = Array.from({ length: Math.max(pageCount - 1, 0) }, (_, index) => index + 2);
  const rest = await mapLimited(pages, PAGE_FAN_OUT, (page) =>
    fetchDocuments({ q: "", page, pageSize }, signal),
  );
  return [first, ...rest].flatMap((response) => response.items);
}

// The live counts by status from /status, so they change during a pass without the list.
export function liveCounts(stats: StatusResponse): Record<DocumentStatus, number> {
  const counts = stats.document_counts;
  return {
    stored: counts.stored ?? 0,
    ingesting: counts.ingesting ?? 0,
    ingested: counts.ingested ?? 0,
    failed: counts.failed ?? 0,
  };
}

export function fetchCorpusStats(signal?: AbortSignal): Promise<StatusResponse> {
  return getJson<StatusResponse>("/status", signal);
}

// 202: started. 409: a pass is already running. Both leave a pass running.
export async function startIngestion(): Promise<void> {
  const { status } = await sendJson("POST", "/ingestion");
  if ((status < 200 || status >= 300) && status !== 409) {
    throw new Error(`POST ingestion returned ${status}`);
  }
}

export type StatusData = {
  documents: DocumentSummary[];
  stats: StatusResponse;
  settings: SettingsResponse;
};

// The documents with the most pages, largest first. Documents without a page count are left out.
export function largestByPages(documents: DocumentSummary[], limit = 8): DocumentSummary[] {
  return documents
    .filter((document) => (document.page_count ?? 0) > 0)
    .toSorted((a, b) => (b.page_count ?? 0) - (a.page_count ?? 0))
    .slice(0, limit);
}

// Ingested documents per UTC day, oldest first, for the most recent days.
export function ingestedPerDay(
  documents: DocumentSummary[],
  days = PER_DAY_DAYS,
): { day: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const document of documents) {
    if (!document.ingested_at) continue;
    const day = document.ingested_at.slice(0, 10);
    counts.set(day, (counts.get(day) ?? 0) + 1);
  }
  return [...counts.entries()]
    .toSorted(([a], [b]) => a.localeCompare(b))
    .slice(-days)
    .map(([day, count]) => ({ day, count }));
}
