import type { BadgeTone } from "@geomak/ui";
import type { DocumentStatus, QueueResponse } from "@/lib/contract/generated";

export const DOCUMENT_TONES: Record<DocumentStatus, BadgeTone> = {
  stored: "neutral",
  ingesting: "info",
  ingested: "success",
  failed: "error",
};

export const QUEUE_TONES: Record<QueueResponse["items"][number]["status"], BadgeTone> = {
  queued: "info",
  added: "success",
  failed: "error",
};
