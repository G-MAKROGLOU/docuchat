"use client";

import { Badge, Button, Card, LoadingSpinner } from "@geomak/ui";
import { Trash } from "@geomak/ui/icons";
import { useRef, useState } from "react";
import type { QueueResponse } from "@/lib/contract/generated";
import { parseTitle } from "@/lib/labelTitle";
import { QUEUE_PAGE_SIZE, removeLabel } from "@/lib/labels";
import { QUEUE_TONES } from "@/lib/statusTones";
import styles from "./CorpusLabels.module.css";
import { LabelName } from "./LabelName";
import type { Queue } from "@/hooks/corpus/useQueue";

// The left border of a queue row shows its state: orange waits for a pass, green is added.
const ROW_CLASS: Record<QueueResponse["items"][number]["status"], string | undefined> = {
  queued: styles.queued,
  added: styles.added,
  failed: undefined,
};

export function QueueCard({ queue, data }: { queue: Queue; data: QueueResponse }) {
  const [message, setMessage] = useState<string | null>(null);
  const heading = useRef<HTMLSpanElement>(null);
  const { page, setPage, reload, loading, error } = queue;

  const remove = async (setId: string) => {
    let removed: boolean;
    try {
      removed = await removeLabel(setId);
    } catch {
      removed = false;
    }
    if (!removed) {
      setMessage("The entry could not be removed.");
      return;
    }
    setMessage(null);
    // The removed button leaves the list, so the focus goes to the heading of the list.
    heading.current?.focus();
    // The last entry of a later page is gone: go back one page. Otherwise load the page again.
    if (data.items.length === 1 && page > 1) setPage(page - 1);
    else reload();
  };

  const pageCount = Math.max(1, Math.ceil(data.total / QUEUE_PAGE_SIZE));
  return (
    <Card>
      <Card.Header
        title={
          <span ref={heading} tabIndex={-1}>
            Queue
          </span>
        }
        subtitle={`${data.queued_total} queued, ${data.added_total} added, ${data.failed_total} failed. Each pass takes the next ${data.labels_per_pass}.`}
      />
      <Card.Body>
        {message ? <output className={styles.message}>{message}</output> : null}
        {error ? (
          <output className={styles.message}>
            The queue could not be refreshed.{" "}
            <Button content="Try again" variant="ghost" size="sm" onClick={reload} />
          </output>
        ) : null}
        {data.items.length === 0 ? (
          <p className={styles.empty}>No labels in the queue.</p>
        ) : (
          <ul className={styles.list} aria-label="Label queue" aria-busy={loading}>
            {data.items.map((item) => {
              const name = parseTitle(item.title)?.name || item.title;
              return (
                <li key={item.set_id} className={ROW_CLASS[item.status]}>
                  <LabelName title={item.title} problem={item.failure_reason} />
                  <span className={styles.actions}>
                    <Badge tone={QUEUE_TONES[item.status]} variant="solid" size="sm">
                      {item.status}
                    </Badge>
                    {item.status === "added" ? null : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className={styles.remove}
                        icon={<Trash size={16} />}
                        aria-label={`Remove ${name} from the queue`}
                        onClick={() => remove(item.set_id)}
                      />
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {loading ? <LoadingSpinner inline size="sm" /> : null}
        {pageCount > 1 ? (
          <nav className={styles.pager} aria-label="Queue pages">
            <Button
              content="Previous"
              size="sm"
              variant="ghost"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            />
            <span className={styles.note}>
              Page {page} of {pageCount}
            </span>
            <Button
              content="Next"
              size="sm"
              variant="ghost"
              disabled={page >= pageCount}
              onClick={() => setPage(page + 1)}
            />
          </nav>
        ) : null}
      </Card.Body>
    </Card>
  );
}
