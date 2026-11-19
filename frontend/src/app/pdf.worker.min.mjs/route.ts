// Serves the worker of the pinned pdfjs-dist, so the viewer needs no CDN.
// force-static: the build writes the file once; dev reads it per request. Nothing is written into src.
import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const dynamic = "force-static";

const WORKER = join(process.cwd(), "node_modules/pdfjs-dist/build/pdf.worker.min.mjs");

export async function GET(): Promise<Response> {
  return new Response(await readFile(WORKER), {
    headers: {
      "content-type": "text/javascript; charset=utf-8",
      "cache-control": "public, max-age=31536000, immutable",
    },
  });
}
