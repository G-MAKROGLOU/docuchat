// Server-sent event types for the answer stream.
// KEEP IN SYNC with docuchat-backend: app/api/schemas/stream.py. A change here needs the same change there.

export type Stage = "rewrite" | "retrieve" | "grade" | "generate";
export type RefusalReason = "no_relevant_context" | "no_valid_citation" | "out_of_scope";

export interface StatusEvent {
  type: "status";
  stage: Stage;
  message: string;
}

export interface Source {
  id: string;
  document: string;
  drug: string;
  section: string;
  page: number;
  text: string;
}

export interface SourcesEvent {
  type: "sources";
  items: Source[];
}

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface FinalEvent {
  type: "final";
  answer: string;
  citations: string[];
}

export interface RefusalEvent {
  type: "refusal";
  reason: RefusalReason;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type StreamEvent =
  StatusEvent | SourcesEvent | TokenEvent | FinalEvent | RefusalEvent | ErrorEvent;
