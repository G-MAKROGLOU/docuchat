"use client";

import { Card, Dropdown, NumberInput } from "@geomak/ui";
import type { SettingsOptions } from "@/lib/contract/generated";
import { choices, LIMITS } from "@/lib/settings";
import { SectionFooter } from "./SectionFooter";
import { ChunkEffects, Help } from "./settingsCopy";
import styles from "./SettingsForm.module.css";
import type { SettingsState } from "@/hooks/settings/useSettings";

export function IndexingCard({
  state,
  options,
}: {
  state: SettingsState;
  options: SettingsOptions;
}) {
  const { draft, set } = state;
  const fields = state.candidate("indexing");
  const overlapError =
    fields && fields.overlap_tokens >= fields.chunk_tokens
      ? "Overlap must be smaller than the chunk size."
      : undefined;
  return (
    <Card>
      <Card.Header
        title="Indexing"
        subtitle="How labels are cut into chunks and embedded. A chunk is a piece of a label. Each chunk is embedded, searched, and shown to the model as an excerpt. A change embeds every document again."
      />
      <Card.Body>
        <div className={styles.row}>
          <NumberInput
            label="Chunk size (tokens)"
            htmlFor="chunk-tokens"
            value={draft.chunk_tokens ?? ""}
            min={LIMITS.chunk_tokens.min}
            max={LIMITS.chunk_tokens.max}
            step={50}
            onChange={({ target }) => set("chunk_tokens", target.value)}
          />
          <NumberInput
            label="Overlap (tokens)"
            htmlFor="overlap-tokens"
            value={draft.overlap_tokens ?? ""}
            min={LIMITS.overlap_tokens.min}
            max={LIMITS.overlap_tokens.max}
            step={10}
            errorMessage={overlapError}
            onChange={({ target }) => set("overlap_tokens", target.value)}
          />
        </div>
        <ChunkEffects />
        <div className={styles.field}>
          <Dropdown
            label="Embedding model"
            layout="vertical"
            htmlFor="embedding-model"
            items={choices(options.embedding_models, draft.embedding_model)}
            value={draft.embedding_model}
            onChange={({ target }) => set("embedding_model", String(target.value))}
          />
        </div>
        <Help>
          The model that turns each chunk and each question into a vector. These models give vectors
          of the size of the index (1536 values). Models differ in quality and in price per token.
          Search compares a question only with vectors of the same model, so after a change chat
          cannot answer until every document is embedded again.
        </Help>
      </Card.Body>
      <SectionFooter section="indexing" state={state} />
    </Card>
  );
}
