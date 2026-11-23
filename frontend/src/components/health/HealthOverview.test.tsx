import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HealthOverview } from "./HealthOverview";

const HEALTHY = {
  status: "ok",
  database: { connected: true, extensions: ["vector", "pg_search", "postgis"] },
};
const NOT_READY = {
  status: "not_ready",
  checks: [
    { name: "database", ok: true, required: true, detail: null, duration_ms: 2.4 },
    { name: "storage", ok: false, required: true, detail: "Bucket not reachable", duration_ms: 31 },
    { name: "worker", ok: false, required: false, detail: "no heartbeat", duration_ms: 3 },
  ],
};

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stubBackend(answers: Record<string, () => Promise<Response>>) {
  const fetchMock = vi.fn<typeof fetch>((url) => {
    const answer = answers[String(url)];
    if (!answer) throw new Error(`unexpected ${String(url)}`);
    return answer();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const URLS = {
  grafanaUrl: "http://localhost:3001",
  prometheusUrl: "http://127.0.0.1:9090",
  langfuseUrl: null,
};

describe("HealthOverview", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the health answer, every readiness check and the monitoring links", async () => {
    stubBackend({
      "/api/v1/health": async () => json(HEALTHY, 200),
      "/api/v1/ready": async () => json(NOT_READY, 503),
    });

    render(<HealthOverview {...URLS} />);

    expect(await screen.findByText("HTTP 503", { exact: false })).toBeTruthy();
    const extensions = screen.getByRole("list", { name: "Postgres extensions" });
    expect(within(extensions).getByText("vector")).toBeTruthy();
    expect(within(extensions).getByText("The semantic half of the hybrid search.")).toBeTruthy();
    expect(within(extensions).getByText("Not used by DocuChat.")).toBeTruthy();
    const checks = screen.getByRole("list", { name: "Readiness checks" });
    expect(within(checks).getByText("storage")).toBeTruthy();
    expect(within(checks).getByText("Bucket not reachable.", { exact: false })).toBeTruthy();
    expect(screen.getAllByText("Failing").length).toBeGreaterThanOrEqual(2);
    // A failed optional check is a warning, not a failure.
    expect(within(checks).getByText("Warning")).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Grafana/ }).getAttribute("href")).toBe(
      URLS.grafanaUrl,
    );
    const tiles = within(screen.getByRole("list", { name: "Monitoring tools" }));
    expect(tiles.getAllByRole("link")).toHaveLength(3);
    expect(screen.getByRole("link", { name: /^Prometheus targets/ }).getAttribute("href")).toBe(
      `${URLS.prometheusUrl}/targets`,
    );
  });

  it("adds a Langfuse tile when its URL is set", async () => {
    stubBackend({
      "/api/v1/health": async () => json(HEALTHY, 200),
      "/api/v1/ready": async () => json({ status: "ready", checks: [] }, 200),
    });

    render(<HealthOverview {...URLS} langfuseUrl="https://cloud.example/project/p1" />);
    await screen.findAllByText("OK");

    const tiles = within(screen.getByRole("list", { name: "Monitoring tools" }));
    expect(tiles.getAllByRole("link")).toHaveLength(4);
    expect(screen.getByRole("link", { name: /^Langfuse/ }).getAttribute("href")).toBe(
      "https://cloud.example/project/p1",
    );
  });

  it("says when the backend has no readiness endpoint or cannot be reached", async () => {
    stubBackend({
      "/api/v1/health": () => Promise.reject(new TypeError("fetch failed")),
      "/api/v1/ready": async () => new Response("Not Found", { status: 404 }),
    });

    render(<HealthOverview {...URLS} />);

    expect(await screen.findByText("Unreachable")).toBeTruthy();
    expect(screen.getByText("Not available")).toBeTruthy();
    expect(screen.getByText("This backend has no readiness endpoint yet.")).toBeTruthy();
  });

  it("checks again on request", async () => {
    const fetchMock = stubBackend({
      "/api/v1/health": async () => json(HEALTHY, 200),
      "/api/v1/ready": async () => json({ status: "ready", checks: [] }, 200),
    });
    render(<HealthOverview {...URLS} />);
    await screen.findAllByText("OK");

    fireEvent.click(screen.getByRole("button", { name: "Check again" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });
});
