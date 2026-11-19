// Copies the pdf.js worker of the pinned pdfjs-dist into public/, so the app serves it (no CDN).
// Plain read and write: copyFile fails with EPERM on Docker Desktop bind mounts when the file exists.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";

const TARGET = "public/pdf.worker.min.mjs";
const source = await readFile(
  createRequire(import.meta.url).resolve("pdfjs-dist/build/pdf.worker.min.mjs"),
);
const current = await readFile(TARGET).catch(() => null);
if (current?.equals(source)) {
  console.log(`${TARGET} is up to date`);
} else {
  await mkdir("public", { recursive: true });
  await writeFile(TARGET, source);
  console.log(`copied pdf.worker.min.mjs to ${TARGET}`);
}
