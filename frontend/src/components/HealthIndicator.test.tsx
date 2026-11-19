import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HealthIndicator } from "./HealthIndicator";

function mockFetch(body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
}

describe("HealthIndicator", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows ok when the backend reports ok", async () => {
    mockFetch({ status: "ok", database: { connected: true, extensions: [] } });
    render(<HealthIndicator />);
    expect(await screen.findByText("Backend: ok")).toBeTruthy();
  });

  it("shows unreachable when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<HealthIndicator />);
    expect(await screen.findByText("Backend: unreachable")).toBeTruthy();
  });
});
