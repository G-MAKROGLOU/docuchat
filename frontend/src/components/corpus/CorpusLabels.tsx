"use client";

import { LoadState } from "@/components/layout/LoadState";
import { PageHeading } from "@/components/layout/PageHeading";
import { AddLabelCard } from "./AddLabelCard";
import styles from "./CorpusLabels.module.css";
import { QueueCard } from "./QueueCard";
import { useQueue } from "@/hooks/corpus/useQueue";

export function CorpusLabels() {
  const queue = useQueue();
  const header = (
    <PageHeading
      title="Corpus"
      note="Labels to add from DailyMed. Each ingestion pass takes the next queued labels."
    />
  );

  if (!queue.data) {
    return (
      <>
        {header}
        <LoadState error={queue.error} label="queue" onRetry={queue.reload} />
      </>
    );
  }
  return (
    <>
      {header}
      <div className={styles.page}>
        <AddLabelCard queued={queue.data.items} onAdded={queue.showFirstPage} />
        <QueueCard queue={queue} data={queue.data} />
      </div>
    </>
  );
}
