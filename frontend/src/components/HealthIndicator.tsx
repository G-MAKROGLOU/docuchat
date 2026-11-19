"use client";

import { Badge, type BadgeTone } from "@geomak/ui";
import { useEffect, useState } from "react";

type State = "checking" | "ok" | "degraded" | "unreachable";

const VIEW: Record<State, { tone: BadgeTone; label: string }> = {
  checking: { tone: "neutral", label: "Backend: checking" },
  ok: { tone: "success", label: "Backend: ok" },
  degraded: { tone: "warning", label: "Backend: database down" },
  unreachable: { tone: "error", label: "Backend: unreachable" },
};

export function HealthIndicator() {
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/health", { signal: controller.signal, cache: "no-store" })
      .then((res) => res.json() as Promise<{ status?: string }>)
      .then((body) =>
        setState(body.status === "ok" || body.status === "degraded" ? body.status : "unreachable"),
      )
      .catch(() => {
        if (!controller.signal.aborted) setState("unreachable");
      });
    return () => controller.abort();
  }, []);

  const { tone, label } = VIEW[state];
  return (
    <output aria-live="polite">
      <Badge tone={tone}>{label}</Badge>
    </output>
  );
}
