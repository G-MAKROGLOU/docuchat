// @vitest-environment node
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";
import { PDF_WORKER_SRC } from "@/lib/pdf";
import { GET } from "./route";

describe("pdf.js worker route", () => {
  it("serves the worker file of the pinned pdfjs-dist as JavaScript", async () => {
    const response = await GET();
    const expected = await readFile(
      createRequire(import.meta.url).resolve("pdfjs-dist/build/pdf.worker.min.mjs"),
    );

    expect(response.headers.get("content-type")).toContain("text/javascript");
    expect(Buffer.from(await response.arrayBuffer()).equals(expected)).toBe(true);
    expect(PDF_WORKER_SRC).toBe("/pdf.worker.min.mjs");
  });
});
