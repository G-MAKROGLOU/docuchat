// @vitest-environment node
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { GET, HEAD } from "./route";

let server: Server;
let releaseSecondEvent: () => void = () => {};

beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url === "/api/v1/moved") {
      res.writeHead(307, { location: `${process.env.BACKEND_URL}/api/v1/health?x=1` });
      res.end();
      return;
    }
    if (req.url === "/api/v1/stream") {
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.write('data: {"type":"token","text":"one"}\n\n');
      // The second event waits until the test has received the first one.
      releaseSecondEvent = () => {
        res.end('data: {"type":"token","text":"two"}\n\n');
      };
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ path: req.url }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  process.env.BACKEND_URL = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(() => {
  server.close();
});

async function readRest(reader: ReadableStreamDefaultReader<string>): Promise<string> {
  const chunk = await reader.read();
  return chunk.done ? "" : chunk.value + (await readRest(reader));
}

function call(path: string[], query = "") {
  const request = new Request(`http://frontend.test/api/${path.join("/")}${query}`);
  return GET(request, { params: Promise.resolve({ path }) });
}

describe("API proxy route", () => {
  it("forwards the path and query to BACKEND_URL", async () => {
    const response = await call(["v1", "health"], "?x=1");

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ path: "/api/v1/health?x=1" });
  });

  it("passes SSE events through one by one", async () => {
    const response = await call(["v1", "stream"]);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();

    // Arrives before the backend sends the second event, so nothing is buffered.
    const first = await reader.read();
    expect(first.value).toContain('"text":"one"');

    releaseSecondEvent();
    expect(await readRest(reader)).toContain('"text":"two"');
  });

  it("rewrites a redirect to the backend host into a relative URL", async () => {
    const response = await call(["v1", "moved"]);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("/api/v1/health?x=1");
  });

  it("forwards HEAD requests", async () => {
    const request = new Request("http://frontend.test/api/v1/health", { method: "HEAD" });
    const response = await HEAD(request, { params: Promise.resolve({ path: ["v1", "health"] }) });

    expect(response.status).toBe(200);
  });

  it("returns 502 when the backend is unreachable", async () => {
    const saved = process.env.BACKEND_URL;
    process.env.BACKEND_URL = "http://127.0.0.1:9";
    try {
      const response = await call(["v1", "health"]);
      expect(response.status).toBe(502);
    } finally {
      process.env.BACKEND_URL = saved;
    }
  });
});
