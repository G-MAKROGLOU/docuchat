import { probeJson } from "@/lib/api";
import type { HealthResponse, ReadyResponse } from "@/lib/contract/generated";

// One endpoint answer. `status` is null when the backend could not be reached at all.
export type Probe<T> = { status: number | null; body: T | null; ms: number };

async function probe<T>(path: string, signal: AbortSignal): Promise<Probe<T>> {
  const started = performance.now();
  try {
    const { status, body } = await probeJson(path, signal);
    return { status, body: body as T | null, ms: performance.now() - started };
  } catch (error) {
    if (signal.aborted) throw error;
    return { status: null, body: null, ms: performance.now() - started };
  }
}

export type HealthData = {
  health: Probe<HealthResponse>;
  ready: Probe<ReadyResponse>;
  checkedAt: Date;
};

export async function fetchHealth(signal: AbortSignal): Promise<HealthData> {
  const [health, ready] = await Promise.all([
    probe<HealthResponse>("/health", signal),
    probe<ReadyResponse>("/ready", signal),
  ]);
  return { health, ready, checkedAt: new Date() };
}

// What each Postgres extension does here. The health check lists what the database has loaded.
export const EXTENSION_INFO: Record<string, { what: string; why: string }> = {
  vector: {
    what: "pgvector: stores embeddings and finds the nearest ones with an HNSW index.",
    why: "The semantic half of the hybrid search.",
  },
  pg_search: {
    what: "ParadeDB BM25 full-text index.",
    why: "The keyword half of the hybrid search, for exact drug names, doses and terms.",
  },
  pg_stat_statements: {
    what: "Records the time and the call count of each SQL statement.",
    why: "Finds slow queries in load tests and in production.",
  },
  plpgsql: {
    what: "The procedural language of Postgres, built into every database.",
    why: "pg_search has a function written in it, so the BM25 index needs it.",
  },
};
