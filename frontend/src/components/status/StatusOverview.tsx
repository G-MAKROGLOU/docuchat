"use client";

import { Button } from "@geomak/ui";
import { Play } from "@geomak/ui/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { LoadState } from "@/components/layout/LoadState";
import { PageHeading } from "@/components/layout/PageHeading";
import { useLoad } from "@/hooks/useLoad";
import type { StatusResponse } from "@/lib/contract/generated";
import { fetchSettings } from "@/lib/settings";
import { fetchAllDocuments, fetchCorpusStats, startIngestion } from "@/lib/status";
import { StatusDashboard } from "./StatusDashboard";
import styles from "./StatusOverview.module.css";

export const POLL_MS = 3000;

// `run` is the restart that gave the values, so a failure of an older run does not show.
type Stats = { value: StatusResponse | null; failed: boolean; run: number };

// Loads /status, then asks again POLL_MS after each answer while a pass runs. Only one request
// is in flight: the next one starts after the previous answer, and a restart aborts the old one.
function useStats(onPassEnd: () => void) {
  const [stats, setStats] = useState<Stats>({ value: null, failed: false, run: 0 });
  const [restarts, setRestarts] = useState(0);
  // A ref, so a restart knows that a pass was running before it.
  const running = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () => {
      fetchCorpusStats(controller.signal).then(
        (value) => {
          setStats({ value, failed: false, run: restarts });
          const ended = running.current && !value.ingestion_running;
          running.current = value.ingestion_running;
          if (ended) onPassEnd();
          if (value.ingestion_running) timer = setTimeout(poll, POLL_MS);
        },
        () => {
          if (controller.signal.aborted) return;
          setStats((previous) => ({ value: previous.value, failed: true, run: restarts }));
          // A failed poll during a pass tries again; a failed first load waits for a retry.
          if (running.current) timer = setTimeout(poll, POLL_MS);
        },
      );
    };
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [restarts, onPassEnd]);

  const restart = useCallback((passStarted: boolean) => {
    if (passStarted) running.current = true;
    setRestarts((n) => n + 1);
  }, []);
  return { value: stats.value, failed: stats.failed && stats.run === restarts, restart };
}

export function StatusOverview() {
  const [startFailed, setStartFailed] = useState(false);
  // The document list loads once, and once more when a pass ends.
  const [passes, setPasses] = useState(0);
  const onPassEnd = useCallback(() => setPasses((n) => n + 1), []);
  const documents = useLoad(`documents:${passes}`, fetchAllDocuments);
  const settings = useLoad("settings", fetchSettings);
  const stats = useStats(onPassEnd);

  const running = stats.value?.ingestion_running ?? false;
  const runIngestion = async () => {
    setStartFailed(false);
    try {
      await startIngestion();
      stats.restart(true);
    } catch {
      setStartFailed(true);
    }
  };

  const ready = documents.data && settings.data && stats.value;
  const header = (
    <div className={styles.header}>
      <PageHeading title="Status" note="Ingestion state of the document corpus." />
      {ready ? (
        <div className={styles.actions}>
          {startFailed ? (
            <output className={styles.meta}>Ingestion could not be started.</output>
          ) : null}
          <Button
            content={running ? "Ingestion running" : "Run ingestion now"}
            size="sm"
            icon={<Play size={14} />}
            loading={running}
            onClick={runIngestion}
          />
        </div>
      ) : null}
    </div>
  );

  if (!documents.data || !settings.data || !stats.value) {
    const retry = () => {
      if (documents.error) documents.reload();
      if (settings.error) settings.reload();
      if (stats.failed) stats.restart(false);
    };
    return (
      <>
        {header}
        <LoadState
          error={documents.error || settings.error || stats.failed}
          label="status"
          onRetry={retry}
        />
      </>
    );
  }

  return (
    <>
      {header}
      {stats.failed || documents.error ? (
        <output className={styles.meta}>
          The status could not be refreshed. It shows the last known values.
        </output>
      ) : null}
      <StatusDashboard
        data={{ documents: documents.data, stats: stats.value, settings: settings.data }}
      />
    </>
  );
}
