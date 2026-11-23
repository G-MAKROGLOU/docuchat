import { API_BASE, getJson } from "@/lib/api";
import type { DocumentListResponse, DocumentSummary } from "@/lib/contract/generated";

type DocumentQuery = { q: string; page: number; pageSize: number };

// The largest page size that GET /documents accepts.
export const MAX_PAGE_SIZE = 100;

// Some labels have no brand name; the generic name is the title then.
export function documentTitle(document: Pick<DocumentSummary, "brand_name" | "generic_name">) {
  return document.brand_name.trim() || document.generic_name;
}

// A combination product lists its ingredients as "a and b" or "a, b".
export function activeIngredients(genericName: string): string[] {
  return genericName
    .split(/,|\band\b/i)
    .map((part) => part.trim())
    .filter(Boolean);
}

function documentsPath({ q, page, pageSize }: DocumentQuery): string {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  const term = q.trim();
  if (term) params.set("q", term);
  return `/documents?${params}`;
}

export function documentsUrl(query: DocumentQuery): string {
  return `${API_BASE}${documentsPath(query)}`;
}

// Change this when the backend thumbnail size changes; browsers cache thumbnails for a day.
const THUMBNAIL_VERSION = "2";

export function thumbnailUrl(documentId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/thumbnail?v=${THUMBNAIL_VERSION}`;
}

// The backend names the attachment by the document title.
export function downloadUrl(documentId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/file?download=1`;
}

export function fetchDocuments(
  query: DocumentQuery,
  signal?: AbortSignal,
): Promise<DocumentListResponse> {
  return getJson<DocumentListResponse>(documentsPath(query), signal);
}
