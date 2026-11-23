import { getJson, sendJson } from "@/lib/api";
import type {
  SettingsOptions,
  SettingsResponse,
  SettingsSaved,
  SettingsUpdate,
} from "@/lib/contract/generated";

export type SettingsFields = SettingsResponse;

export const LIMITS = {
  chunk_tokens: { min: 100, max: 2000 },
  overlap_tokens: { min: 0, max: 500 },
  top_k: { min: 5, max: 50 },
} as const;

const MODEL_NAME = /^[A-Za-z0-9._:/-]{1,100}$/;

export function toFields(response: SettingsResponse): SettingsFields {
  return {
    chunk_tokens: response.chunk_tokens,
    overlap_tokens: response.overlap_tokens,
    top_k: response.top_k,
    embedding_model: response.embedding_model,
    chat_model: response.chat_model,
    rewrite_model: response.rewrite_model,
    grade_model: response.grade_model,
    generate_model: response.generate_model,
    reasoning_effort: response.reasoning_effort,
    grader_mode: response.grader_mode,
  };
}

function inRange(value: number, limit: { min: number; max: number }): boolean {
  return Number.isInteger(value) && value >= limit.min && value <= limit.max;
}

// The same rules as the API, so the form can say what is wrong before it saves.
export function isValid(fields: SettingsFields): boolean {
  return (
    inRange(fields.chunk_tokens, LIMITS.chunk_tokens) &&
    inRange(fields.overlap_tokens, LIMITS.overlap_tokens) &&
    fields.overlap_tokens < fields.chunk_tokens &&
    inRange(fields.top_k, LIMITS.top_k) &&
    [
      fields.embedding_model,
      fields.chat_model,
      fields.rewrite_model,
      fields.grade_model,
      fields.generate_model,
    ].every((name) => MODEL_NAME.test(name))
  );
}

// Each chunk starts (size - overlap) tokens after the one before, so the count follows that step.
export function estimateChunks(
  chunkCount: number,
  from: SettingsFields,
  to: SettingsFields,
): number {
  const fromStep = from.chunk_tokens - from.overlap_tokens;
  const toStep = to.chunk_tokens - to.overlap_tokens;
  return Math.round((chunkCount * fromStep) / toStep);
}

// A number field holds undefined while it is empty, so the user can retype it.
export type Draft = Omit<SettingsFields, "chunk_tokens" | "overlap_tokens" | "top_k"> & {
  chunk_tokens?: number;
  overlap_tokens?: number;
  top_k?: number;
};

export function complete(draft: Draft): SettingsFields | null {
  const { chunk_tokens, overlap_tokens, top_k } = draft;
  if (chunk_tokens === undefined || overlap_tokens === undefined || top_k === undefined) {
    return null;
  }
  return { ...draft, chunk_tokens, overlap_tokens, top_k };
}

// Each card saves its own fields. The other cards keep their unsaved edits.
export type Section = "indexing" | "search" | "models" | "checking";

export const SECTION_FIELDS: Record<Section, (keyof SettingsFields)[]> = {
  indexing: ["chunk_tokens", "overlap_tokens", "embedding_model"],
  search: ["top_k"],
  models: ["chat_model", "rewrite_model", "grade_model", "generate_model", "reasoning_effort"],
  checking: ["grader_mode"],
};

export function pick(source: Draft, section: Section): Partial<Draft> {
  return Object.fromEntries(SECTION_FIELDS[section].map((key) => [key, source[key]]));
}

// The ids to choose from. The current value is always there, also when the list is empty.
export function choices(ids: string[], current: string): { key: string; label: string }[] {
  const all = ids.includes(current) ? ids : [current, ...ids];
  return all.map((id) => ({ key: id, label: id }));
}

export function chunksChanged(a: SettingsFields, b: SettingsFields): boolean {
  return a.chunk_tokens !== b.chunk_tokens || a.overlap_tokens !== b.overlap_tokens;
}

export function fetchSettings(signal?: AbortSignal): Promise<SettingsResponse> {
  return getJson<SettingsResponse>("/settings", signal);
}

type SaveOutcome =
  | { kind: "saved"; saved: SettingsSaved }
  | { kind: "confirm" }
  | { kind: "running" }
  | { kind: "failed" };

export async function saveSettings(
  fields: SettingsFields,
  reingestConfirmed: boolean,
): Promise<SaveOutcome> {
  const update: SettingsUpdate = { ...fields, reingest_confirmed: reingestConfirmed };
  const { status, body } = await sendJson("PUT", "/settings", update);
  if (status >= 200 && status < 300) return { kind: "saved", saved: body as SettingsSaved };
  if (status === 409) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    return {
      kind: typeof detail === "string" && detail.includes("running") ? "running" : "confirm",
    };
  }
  return { kind: "failed" };
}

export function fetchOptions(signal?: AbortSignal): Promise<SettingsOptions> {
  return getJson<SettingsOptions>("/settings/options", signal);
}
