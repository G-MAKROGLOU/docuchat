"use client";

import { Card, SearchInput } from "@geomak/ui";
import { Plus } from "@geomak/ui/icons";
import { useState } from "react";
import type { QueueResponse } from "@/lib/contract/generated";
import { type AddOutcome, addLabel, isSetId } from "@/lib/labels";
import styles from "./CorpusLabels.module.css";
import { LabelName } from "./LabelName";
import { useCatalogSearch } from "@/hooks/corpus/useCatalogSearch";

const SEARCH_ID = "label-search";

const MESSAGES: Record<AddOutcome, string> = {
  added: "Added to the queue.",
  unknown: "DailyMed does not know this set ID.",
  known: "The label is already in the corpus or in the queue.",
  failed: "The label could not be added.",
};

export function AddLabelCard({
  queued,
  onAdded,
}: {
  queued: QueueResponse["items"];
  onAdded: () => void;
}) {
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const text = query.trim();
  const search = useCatalogSearch(text);

  const add = async (setId: string) => {
    let outcome: AddOutcome;
    try {
      outcome = await addLabel(setId);
    } catch {
      outcome = "failed";
    }
    setMessage(MESSAGES[outcome]);
    // The clicked result leaves the list, so the focus goes back to the search field.
    document.getElementById(SEARCH_ID)?.focus();
    // The write is saved; a failed refresh shows on the queue card, not here.
    if (outcome === "added") onAdded();
  };

  // A label that was added drops out of the results at once; the API leaves it out of later ones.
  const queuedIds = new Set(queued.map((item) => item.set_id));
  const options = search.labels.filter((label) => !queuedIds.has(label.set_id));

  return (
    <Card>
      <Card.Header
        title="Add a label"
        subtitle="Type a drug name to search DailyMed, or paste a set ID. Click a result to queue it."
      />
      <Card.Body>
        <SearchInput
          value={query}
          onChange={({ target }) => {
            setQuery(target.value);
            setMessage(null);
          }}
          placeholder="Drug name or set ID"
          label="Drug name or set ID"
          htmlFor={SEARCH_ID}
        />
        {search.searching ? <output className={styles.message}>Searching DailyMed</output> : null}
        {search.failed ? (
          <output className={styles.message}>The DailyMed search failed.</output>
        ) : null}
        {message ? <output className={styles.message}>{message}</output> : null}
        {text && isSetId(text) ? (
          <ul className={styles.list} aria-label="DailyMed results">
            <li>
              <button type="button" className={styles.option} onClick={() => add(text)}>
                <span className={styles.title}>
                  <span className={styles.name}>Set ID {text}</span>
                  <span className={styles.meta}>DailyMed checks this ID when you add it</span>
                </span>
                <span className={styles.add}>
                  <Plus size={14} /> Add
                </span>
              </button>
            </li>
          </ul>
        ) : null}
        {search.settled && !search.failed && options.length === 0 ? (
          <output className={styles.message}>DailyMed has no new label for this name.</output>
        ) : null}
        {options.length > 0 ? (
          <>
            <p className={styles.note}>
              {options.length} {options.length === 1 ? "label" : "labels"} from DailyMed. Click one
              to add it to the queue.
            </p>
            <ul className={`${styles.list} ${styles.results}`} aria-label="DailyMed results">
              {options.map((label) => (
                <li key={label.set_id}>
                  <button type="button" className={styles.option} onClick={() => add(label.set_id)}>
                    <LabelName
                      title={label.title}
                      extra={`Version ${label.version}, ${label.published}`}
                    />
                    <span className={styles.add}>
                      <Plus size={14} /> Add
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </Card.Body>
    </Card>
  );
}
