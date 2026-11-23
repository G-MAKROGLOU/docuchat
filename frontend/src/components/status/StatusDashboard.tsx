"use client";

import { Badge, Card, Statistic, Tooltip } from "@geomak/ui";
import { Info } from "@geomak/ui/icons";
import type { DocumentStatus } from "@/lib/contract/generated";
import { documentTitle } from "@/lib/documents";
import { formatDateTime, formatNumber, formatShortDay } from "@/lib/format";
import {
  ingestedPerDay,
  largestByPages,
  PER_DAY_DAYS,
  STATUS_ORDER,
  type StatusData,
  liveCounts,
  summarize,
} from "@/lib/status";
import { DOCUMENT_TONES } from "@/lib/statusTones";
import styles from "./StatusDashboard.module.css";

const SEGMENT_COLORS: Record<DocumentStatus, string> = {
  ingested: "var(--color-success)",
  ingesting: "var(--color-info)",
  stored: "var(--color-border-strong)",
  failed: "var(--color-error)",
};

const PHASE_LABELS: Record<StatusData["stats"]["ingestion_phase"], string> = {
  idle: "Idle",
  checking: "Checking for updates",
  downloading: "Downloading labels",
  ingesting: "Ingesting",
};

const STATE_HELP: Record<DocumentStatus, string> = {
  stored:
    "The file is saved and waiting for ingestion. A document is in one state at a time, so ingested documents are not counted here.",
  ingesting:
    "The document is being read, split into chunks and embedded now. One document at a time.",
  ingested: "The chunks and embeddings are saved. Chat can search and cite this document.",
  failed:
    "The last ingestion failed. The reason is listed under Needs attention. The next pass tries again.",
};

const TOKENS_HELP =
  "Embedding tokens are the text units that the embedding model read to turn the chunks into vectors. " +
  "Ingestion sends every chunk to the model, and the provider bills per token. " +
  "This number is the size of the current index, not the total spent: ingesting a document again spends its tokens again. " +
  "Chat questions also use a few tokens each, but they are not counted here.";

// The chunk size and the overlap are the current settings.
export function chunksHelp(chunkTokens: number, overlapTokens: number): string {
  return (
    `A chunk is a piece of a label of about ${chunkTokens} tokens, with ${overlapTokens} tokens of overlap (the current settings). ` +
    "Search works on chunks, and each chunk is one vector. " +
    "More chunks per document give finer search results and more precise citations, but also more vectors to store and more embedding tokens. " +
    "Long labels give more chunks."
  );
}

function InfoTip({ text, label, small }: { text: string; label: string; small?: boolean }) {
  return (
    <Tooltip title={text} placement="top">
      <button
        type="button"
        className={small ? `${styles.infoTip} ${styles.infoTipSmall}` : styles.infoTip}
        aria-label={label}
      >
        <Info size={14} />
      </button>
    </Tooltip>
  );
}

export function StatusDashboard({ data }: { data: StatusData }) {
  const { documents, stats, settings } = data;
  // Pages, dates and the attention list come from the document list, which loads again when a
  // pass ends. The counts come from /status, so they follow a running pass.
  const summary = summarize(documents);
  const counts = liveCounts(stats);
  const total = STATUS_ORDER.reduce((sum, status) => sum + counts[status], 0);
  const notIngested = total - counts.ingested;
  const largest = largestByPages(documents);
  const perDay = ingestedPerDay(documents, PER_DAY_DAYS);
  const maxPages = largest[0]?.page_count ?? 1;
  const maxPerDay = Math.max(1, ...perDay.map((entry) => entry.count));
  const healthy = notIngested === 0;

  return (
    <div className={styles.dashboard}>
      <div className={styles.kpis}>
        <Card>
          <Card.Body>
            <Statistic label="Documents" value={formatNumber(total)} />
          </Card.Body>
        </Card>
        <Card>
          <Card.Body>
            <Statistic label="Pages" value={formatNumber(summary.pages)} />
          </Card.Body>
        </Card>
        <Card>
          <Card.Body>
            <Statistic label="Chunks" value={formatNumber(stats.chunk_count)} />
          </Card.Body>
        </Card>
        <Card>
          <Card.Body>
            <Statistic
              label={
                <>
                  Embedding tokens
                  <InfoTip text={TOKENS_HELP} label="About embedding tokens" small />
                </>
              }
              value={formatNumber(stats.token_count)}
            />
          </Card.Body>
        </Card>
        <Card>
          <Card.Body>
            <Statistic
              label="Health"
              value={healthy ? "Healthy" : "Needs attention"}
              helpText={healthy ? "All documents are ingested." : `${notIngested} not ingested`}
            />
          </Card.Body>
        </Card>
      </div>

      <div className={styles.panels}>
        <Card>
          <Card.Header title="Ingestion state" subtitle="Documents by state" />
          <Card.Body>
            <div className={styles.stack} aria-hidden="true">
              {STATUS_ORDER.filter((s) => counts[s] > 0).map((s) => (
                <span key={s} style={{ flexGrow: counts[s], background: SEGMENT_COLORS[s] }} />
              ))}
            </div>
            <ul className={styles.legend}>
              {STATUS_ORDER.map((s) => (
                <li key={s}>
                  <span className={styles.swatch} style={{ background: SEGMENT_COLORS[s] }} />
                  <span className={styles.legendName}>
                    {s}
                    <InfoTip text={STATE_HELP[s]} label={`About the ${s} state`} />
                  </span>
                  <span className={styles.legendCount}>{counts[s]}</span>
                </li>
              ))}
            </ul>
          </Card.Body>
        </Card>

        <Card>
          <Card.Header
            title="Pipeline"
            action={
              <Badge
                tone={stats.ingestion_phase === "idle" ? "neutral" : "info"}
                variant="solid"
                size="sm"
              >
                {PHASE_LABELS[stats.ingestion_phase]}
              </Badge>
            }
          />
          <Card.Body>
            <dl className={styles.facts}>
              <div>
                <dt>Last ingestion</dt>
                <dd>{formatDateTime(summary.lastIngestedAt)}</dd>
              </div>
              <div>
                <dt>Next scheduled</dt>
                <dd>{formatDateTime(stats.next_run_at)}</dd>
              </div>
              <div>
                <dt>Embedding model</dt>
                <dd>{stats.embedding_models.join(", ") || "None"}</dd>
              </div>
              <div>
                <dt>
                  Chunks per document
                  <InfoTip
                    text={chunksHelp(settings.chunk_tokens, settings.overlap_tokens)}
                    label="About chunks per document"
                  />
                </dt>
                <dd>{total ? formatNumber(Math.round(stats.chunk_count / total)) : 0}</dd>
              </div>
            </dl>
          </Card.Body>
        </Card>

        <Card>
          <Card.Header title="Largest documents" subtitle="Pages" />
          <Card.Body>
            <ul className={styles.bars}>
              {largest.map((document) => (
                <li key={document.id}>
                  <span className={styles.barLabel}>{documentTitle(document)}</span>
                  <span className={styles.track}>
                    <span
                      className={styles.fill}
                      style={{ width: `${((document.page_count ?? 0) / maxPages) * 100}%` }}
                    />
                  </span>
                  <span className={styles.barValue}>{document.page_count}</span>
                </li>
              ))}
            </ul>
          </Card.Body>
        </Card>

        <Card>
          <Card.Header
            title="Ingested per day"
            subtitle={`Last ${PER_DAY_DAYS} days with activity`}
          />
          <Card.Body>
            {perDay.length === 0 ? (
              <p className={styles.empty}>Nothing ingested yet.</p>
            ) : (
              <ul className={styles.columns}>
                {perDay.map((entry) => (
                  <li key={entry.day}>
                    <span className={styles.columnValue}>{entry.count}</span>
                    <span
                      className={styles.column}
                      style={{ height: `${(entry.count / maxPerDay) * 100}%` }}
                    />
                    <span className={styles.columnLabel}>{formatShortDay(entry.day)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card.Body>
        </Card>
      </div>

      {summary.attention.length > 0 ? (
        <Card>
          <Card.Header title="Needs attention" subtitle="Documents that are not ingested" />
          <Card.Body>
            <ul className={styles.attention} aria-label="Documents that are not ingested">
              {summary.attention.map((document) => (
                <li key={document.id}>
                  <span>
                    {documentTitle(document)}
                    {document.failure_reason ? (
                      <span className={styles.reason}>{document.failure_reason}</span>
                    ) : null}
                  </span>
                  <Badge tone={DOCUMENT_TONES[document.status]} variant="solid" size="sm">
                    {document.status}
                  </Badge>
                </li>
              ))}
            </ul>
          </Card.Body>
        </Card>
      ) : null}
    </div>
  );
}
