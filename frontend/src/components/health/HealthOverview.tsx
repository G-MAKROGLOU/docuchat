"use client";

import { Badge, type BadgeTone, Button, Card } from "@geomak/ui";
import { ExternalLink, Refresh } from "@geomak/ui/icons";
import Image from "next/image";
import { useState } from "react";
import { LoadState } from "@/components/layout/LoadState";
import { PageHeading } from "@/components/layout/PageHeading";
import { useLoad } from "@/hooks/useLoad";
import type { ReadyCheck } from "@/lib/contract/generated";
import { formatDateTime } from "@/lib/format";
import { EXTENSION_INFO, type HealthData, type Probe, fetchHealth } from "@/lib/health";
import styles from "./HealthOverview.module.css";

type Verdict = { label: string; tone: BadgeTone };

function verdict(probe: Probe<unknown>, ok: boolean): Verdict {
  if (probe.status === null) return { label: "Unreachable", tone: "error" };
  if (probe.status === 404) return { label: "Not available", tone: "neutral" };
  return ok ? { label: "OK", tone: "success" } : { label: "Failing", tone: "error" };
}

// A failed optional check is a warning: the API stays ready without it.
function checkTone(check: ReadyCheck): BadgeTone {
  if (check.ok) return "success";
  return check.required ? "error" : "warning";
}

function checkLabel(check: ReadyCheck): string {
  if (check.ok) return "OK";
  return check.required ? "Failing" : "Warning";
}

function Answer({ probe }: { probe: Probe<unknown> }) {
  return (
    <p className={styles.answer}>
      {probe.status === null ? "No answer" : `HTTP ${probe.status}`} in {Math.round(probe.ms)} ms
    </p>
  );
}

function HealthCard({ probe }: { probe: HealthData["health"] }) {
  const body = probe.body;
  const state = verdict(probe, probe.status === 200 && body?.status === "ok");
  return (
    <Card>
      <Card.Header
        title="Health"
        subtitle="GET /api/v1/health: the API runs and reaches the database."
        action={<Badge tone={state.tone}>{state.label}</Badge>}
      />
      <Card.Body>
        <Answer probe={probe} />
        {body ? (
          <dl className={styles.facts}>
            <dt>Database</dt>
            <dd>{body.database.connected ? "Connected" : "Not connected"}</dd>
          </dl>
        ) : null}
        {body?.database.extensions.length ? (
          <>
            <p className={styles.subhead}>Postgres extensions</p>
            <ul className={styles.extensions} aria-label="Postgres extensions">
              {body.database.extensions.map((name) => {
                const info = EXTENSION_INFO[name];
                return (
                  <li key={name} className={styles.extension}>
                    <code className={styles.name}>{name}</code>
                    {info ? (
                      <>
                        <span>{info.what}</span>
                        <span className={styles.detail}>{info.why}</span>
                      </>
                    ) : (
                      <span className={styles.detail}>Not used by DocuChat.</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}
      </Card.Body>
    </Card>
  );
}

function ReadyCard({ probe }: { probe: HealthData["ready"] }) {
  const body = probe.body;
  const state = verdict(probe, probe.status === 200 && body?.status === "ready");
  return (
    <Card>
      <Card.Header
        title="Readiness"
        subtitle="GET /api/v1/ready: every dependency that an answer needs."
        action={<Badge tone={state.tone}>{state.label}</Badge>}
      />
      <Card.Body>
        <Answer probe={probe} />
        {probe.status === 404 ? (
          <p className={styles.note}>This backend has no readiness endpoint yet.</p>
        ) : null}
        {body?.checks?.length ? (
          <ul className={styles.checks} aria-label="Readiness checks">
            {body.checks.map((check) => (
              <li key={check.name} className={styles.check}>
                <Badge tone={checkTone(check)}>{checkLabel(check)}</Badge>
                <span className={styles.name}>
                  {check.name}
                  {check.required ? null : <span className={styles.detail}> (optional)</span>}
                </span>
                <span className={styles.detail}>
                  {check.detail ? `${check.detail}. ` : ""}
                  {Math.round(check.duration_ms)} ms
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </Card.Body>
    </Card>
  );
}

type Tool = { href: string; logo: string; label: string; note: string };

// The logo comes from the tool itself, so a tile shows no logo while its tool is down.
function ToolTile({ tool }: { tool: Tool }) {
  const [logoFailed, setLogoFailed] = useState(false);
  return (
    <li>
      <a href={tool.href} target="_blank" rel="noopener noreferrer" className={styles.tile}>
        <span className={styles.logo} aria-hidden>
          {logoFailed ? null : (
            <Image
              unoptimized
              src={tool.logo}
              alt=""
              width={36}
              height={36}
              onError={() => setLogoFailed(true)}
            />
          )}
        </span>
        <span className={styles.tileText}>
          <span className={styles.tileTitle}>
            {tool.label}
            <ExternalLink size={14} aria-hidden />
          </span>
          <span className={styles.detail}>{tool.note}</span>
        </span>
      </a>
    </li>
  );
}

type MonitoringUrls = { grafanaUrl: string; prometheusUrl: string; langfuseUrl: string | null };

function MonitoringCard({ grafanaUrl, prometheusUrl, langfuseUrl }: MonitoringUrls) {
  const grafanaLogo = `${grafanaUrl}/public/img/grafana_icon.svg`;
  const prometheusLogo = `${prometheusUrl}/favicon.svg`;
  const tools: Tool[] = [
    {
      href: grafanaUrl,
      logo: grafanaLogo,
      label: "Grafana",
      note: "Dashboards for requests, chat turns, ingestion and the database pool.",
    },
    {
      href: `${prometheusUrl}/targets`,
      logo: prometheusLogo,
      label: "Prometheus targets",
      note: "Whether Prometheus reaches the backend and the ingestion worker.",
    },
    {
      href: `${prometheusUrl}/query`,
      logo: prometheusLogo,
      label: "Prometheus queries",
      note: "Raw metrics, queried with PromQL.",
    },
  ];
  if (langfuseUrl) {
    tools.push({
      href: langfuseUrl,
      logo: `${new URL(langfuseUrl).origin}/icon.svg`,
      label: "Langfuse",
      note: "Traces of each chat turn: every model call, its prompt, tokens and cost.",
    });
  }
  return (
    <Card>
      <Card.Header title="Monitoring" subtitle="Each tile opens the tool in a new tab." />
      <Card.Body>
        <ul className={styles.tiles} aria-label="Monitoring tools">
          {tools.map((tool) => (
            <ToolTile key={tool.label} tool={tool} />
          ))}
        </ul>
      </Card.Body>
    </Card>
  );
}

export function HealthOverview(urls: MonitoringUrls) {
  const health = useLoad("health", fetchHealth);
  const data = health.data;
  return (
    <div className={styles.page}>
      <div className={styles.top}>
        <PageHeading
          title="Health"
          note={
            data
              ? `Backend checks at ${formatDateTime(data.checkedAt.toISOString())}.`
              : "Backend checks and monitoring."
          }
        />
        <Button
          content="Check again"
          icon={<Refresh size={14} />}
          size="sm"
          variant="secondary"
          onClick={health.reload}
          loading={health.loading}
        />
      </div>
      {data ? (
        <div className={styles.grid}>
          <HealthCard probe={data.health} />
          <ReadyCard probe={data.ready} />
        </div>
      ) : (
        <LoadState error={health.error} label="health checks" onRetry={health.reload} />
      )}
      <MonitoringCard {...urls} />
    </div>
  );
}
