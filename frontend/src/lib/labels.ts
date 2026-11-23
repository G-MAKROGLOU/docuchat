import { getJson, sendJson } from "@/lib/api";
import type { CatalogLabelResponse, QueueResponse } from "@/lib/contract/generated";

const SET_ID = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export function isSetId(text: string): boolean {
  return SET_ID.test(text.trim());
}

export const QUEUE_PAGE_SIZE = 10;

export function fetchQueue(page: number, signal?: AbortSignal): Promise<QueueResponse> {
  return getJson<QueueResponse>(`/labels?page=${page}&page_size=${QUEUE_PAGE_SIZE}`, signal);
}

export function searchCatalog(
  query: string,
  signal?: AbortSignal,
): Promise<CatalogLabelResponse[]> {
  return getJson<CatalogLabelResponse[]>(`/labels/search?q=${encodeURIComponent(query)}`, signal);
}

export type AddOutcome = "added" | "unknown" | "known" | "failed";

export async function addLabel(setId: string): Promise<AddOutcome> {
  const { status } = await sendJson("POST", "/labels", { set_id: setId.trim() });
  if (status === 201) return "added";
  if (status === 404) return "unknown";
  if (status === 409) return "known";
  return "failed";
}

export async function removeLabel(setId: string): Promise<boolean> {
  const { status } = await sendJson("DELETE", `/labels/${encodeURIComponent(setId)}`);
  return status === 204;
}
