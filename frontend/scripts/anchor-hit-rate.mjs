// Anchor hit rate: how often the viewer finds a cited chunk on its PDF page.
// Input: backend/evals/cache/anchors.json (python -m evals.export_anchors). PDFs come from the API.
// Usage: npm run eval:anchors -- [--api http://localhost:8000/api/v1] [--in FILE] [--out FILE]
// One PDF and one search at a time on purpose: it keeps memory low.
/* oxlint-disable no-await-in-loop */
import { readFile, writeFile } from "node:fs/promises";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { searchPdfPhrase } from "@geomak/ui/pdf";

// The same phrases as highlightPhrases in src/components/documents/DocumentViewer.tsx.
const PASSAGE_WORDS = 60;

function option(name, fallback) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : fallback;
}

const api = option("--api", "http://localhost:8000/api/v1");
const input = option("--in", "../backend/evals/cache/anchors.json");
const stamp = new Date().toISOString().slice(0, 10);
const output = option("--out", `../backend/evals/results/${stamp}-anchor-hit-rate.json`);

function phrases(text, anchor) {
  const long = text.split(/\s+/).filter(Boolean).slice(0, PASSAGE_WORDS).join(" ");
  const short = anchor.trim();
  return [long, short].filter((p, i, all) => p && all.indexOf(p) === i);
}

async function openPdf(documentId) {
  const response = await fetch(`${api}/documents/${documentId}/file`);
  if (!response.ok) throw new Error(`PDF ${documentId}: HTTP ${response.status}`);
  const data = new Uint8Array(await response.arrayBuffer());
  // pdfjs 6: the loading task, not the document, has destroy().
  return getDocument({ data, isEvalSupported: false, verbosity: 0 });
}

// What the viewer does: the passage start, then the anchor, on the cited page only.
async function resolve(pdf, chunk) {
  const tried = phrases(chunk.text, chunk.anchor);
  for (const [index, phrase] of tried.entries()) {
    if ((await searchPdfPhrase(pdf, chunk.page, phrase)).found) {
      return { result: index === 0 && tried.length > 1 ? "passage" : "anchor" };
    }
  }
  // Diagnosis only: is the anchor on another page of the chunk, or near it?
  const tolerance = Math.max(1, chunk.pageEnd - chunk.page);
  const near = await searchPdfPhrase(pdf, chunk.page, chunk.anchor, { pageTolerance: tolerance });
  return { result: "miss", foundOnPage: near.found ? near.page : null };
}

const chunks = JSON.parse(await readFile(input, "utf-8"));
const byDocument = Map.groupBy(chunks, (c) => c.document);
const counts = { passage: 0, anchor: 0, miss: 0 };
const misses = [];
const failedDocuments = [];
let done = 0;

for (const [documentId, group] of byDocument) {
  let task, pdf;
  try {
    task = await openPdf(documentId);
    pdf = await task.promise;
  } catch (error) {
    failedDocuments.push({ document: documentId, chunks: group.length, error: String(error) });
    continue;
  }
  try {
    for (const chunk of group) {
      const { result, foundOnPage } = await resolve(pdf, chunk);
      counts[result] += 1;
      if (result === "miss") {
        misses.push({
          chunk: chunk.chunk,
          drug: chunk.drug,
          section: chunk.section,
          page: chunk.page,
          pageEnd: chunk.pageEnd,
          anchor: chunk.anchor,
          foundOnPage,
        });
      }
    }
  } finally {
    await task.destroy();
  }
  done += group.length;
  process.stdout.write(`\r${done}/${chunks.length} chunks`);
}

const checked = counts.passage + counts.anchor + counts.miss;
const missesByDrug = Object.fromEntries(
  [...Map.groupBy(misses, (m) => m.drug)]
    .map(([drug, list]) => [drug, list.length])
    .toSorted((a, b) => b[1] - a[1]),
);
const report = {
  checked,
  hitRate: checked ? (counts.passage + counts.anchor) / checked : 0,
  counts,
  missesOnAnotherPage: misses.filter((m) => m.foundOnPage !== null).length,
  missesByDrug,
  failedDocuments,
  misses,
};
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
console.log(
  `\nhit rate ${(report.hitRate * 100).toFixed(1)}% of ${checked}`,
  counts,
  `misses found on another page: ${report.missesOnAnotherPage}`,
  `failed documents: ${failedDocuments.length}`,
  `\nwrote ${output}`,
);
