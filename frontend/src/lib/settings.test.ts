import { afterEach, describe, expect, it, vi } from "vitest";
import {
  choices,
  chunksChanged,
  complete,
  estimateChunks,
  isValid,
  LIMITS,
  pick,
  saveSettings,
  type SettingsFields,
  toFields,
} from "./settings";

const FIELDS: SettingsFields = {
  chunk_tokens: 500,
  overlap_tokens: 50,
  top_k: 20,
  embedding_model: "m/embed",
  chat_model: "a/chat",
  rewrite_model: "a/rewrite",
  grade_model: "a/grade",
  generate_model: "a/generate",
  reasoning_effort: "low",
  grader_mode: "llm",
};

describe("isValid", () => {
  it.each([
    ["the saved values", {}, true],
    ["the smallest chunk size", { chunk_tokens: LIMITS.chunk_tokens.min }, true],
    ["a chunk size below the limit", { chunk_tokens: LIMITS.chunk_tokens.min - 1 }, false],
    ["the largest chunk size", { chunk_tokens: LIMITS.chunk_tokens.max }, true],
    ["a chunk size above the limit", { chunk_tokens: LIMITS.chunk_tokens.max + 1 }, false],
    ["a chunk size that is not whole", { chunk_tokens: 250.5 }, false],
    ["no overlap", { overlap_tokens: 0 }, true],
    ["a negative overlap", { overlap_tokens: -1 }, false],
    ["an overlap above the limit", { overlap_tokens: LIMITS.overlap_tokens.max + 1 }, false],
    ["an overlap equal to the chunk size", { chunk_tokens: 200, overlap_tokens: 200 }, false],
    ["the smallest top-k", { top_k: LIMITS.top_k.min }, true],
    ["a top-k below the limit", { top_k: LIMITS.top_k.min - 1 }, false],
    ["a top-k above the limit", { top_k: LIMITS.top_k.max + 1 }, false],
    ["a model name with a space", { chat_model: "a chat" }, false],
    ["an empty model name", { generate_model: "" }, false],
    ["a model name with a colon and a dot", { grade_model: "x/model-1.5:free" }, true],
  ])("%s", (_, change, valid) => {
    expect(isValid({ ...FIELDS, ...change })).toBe(valid);
  });
});

describe("estimateChunks", () => {
  it("scales the chunk count by the step between chunk starts", () => {
    // Step 450 to step 225: twice as many chunks.
    expect(estimateChunks(1000, FIELDS, { ...FIELDS, chunk_tokens: 250, overlap_tokens: 25 })).toBe(
      2000,
    );
  });

  it("rounds to a whole chunk", () => {
    // 100 * 450 / 400 = 112.5
    expect(estimateChunks(100, FIELDS, { ...FIELDS, chunk_tokens: 450, overlap_tokens: 50 })).toBe(
      113,
    );
  });
});

describe("form helpers", () => {
  it("completes a draft only when every number field has a value", () => {
    expect(complete(FIELDS)).toEqual(FIELDS);
    expect(complete({ ...FIELDS, top_k: undefined })).toBeNull();
  });

  it("picks the fields of one section", () => {
    expect(pick(FIELDS, "search")).toEqual({ top_k: 20 });
    expect(pick(FIELDS, "checking")).toEqual({ grader_mode: "llm" });
  });

  it("offers the current value also when the list does not have it", () => {
    expect(choices([], "a/x")).toEqual([{ key: "a/x", label: "a/x" }]);
    expect(choices(["a/x", "a/y"], "a/y").map((c) => c.key)).toEqual(["a/x", "a/y"]);
  });

  it("sees a chunk change in the size or the overlap only", () => {
    expect(chunksChanged(FIELDS, { ...FIELDS, top_k: 30 })).toBe(false);
    expect(chunksChanged(FIELDS, { ...FIELDS, overlap_tokens: 0 })).toBe(true);
  });

  it("keeps only the settings fields of a response", () => {
    expect(toFields({ ...FIELDS, extra: 1 } as SettingsFields)).toEqual(FIELDS);
  });
});

function answer(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("saveSettings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the fields with the approval and returns the saved settings", async () => {
    const fetchMock = answer(Response.json({ ...FIELDS, reingest_started: false }));

    const outcome = await saveSettings(FIELDS, true);

    expect(outcome).toEqual({ kind: "saved", saved: { ...FIELDS, reingest_started: false } });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/settings");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ ...FIELDS, reingest_confirmed: true });
  });

  it("tells a running pass from a missing approval on 409", async () => {
    answer(Response.json({ detail: "An ingestion pass is running." }, { status: 409 }));
    expect(await saveSettings(FIELDS, false)).toEqual({ kind: "running" });

    answer(Response.json({ detail: "Confirm the re-ingestion." }, { status: 409 }));
    expect(await saveSettings(FIELDS, false)).toEqual({ kind: "confirm" });

    answer(new Response(null, { status: 409 }));
    expect(await saveSettings(FIELDS, false)).toEqual({ kind: "confirm" });
  });

  it("reports other errors as failed", async () => {
    answer(Response.json({ detail: "bad" }, { status: 422 }));
    expect(await saveSettings(FIELDS, false)).toEqual({ kind: "failed" });
  });
});
