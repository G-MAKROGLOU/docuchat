"use client";

import { Modal } from "@geomak/ui";
import { formatNumber } from "@/lib/format";
import { chunksChanged, estimateChunks } from "@/lib/settings";
import styles from "./SettingsForm.module.css";
import type { Loaded, SettingsState } from "@/hooks/settings/useSettings";

// The approval to embed every document again, with what the change does to the index.
export function ReindexModal({ state, loaded }: { state: SettingsState; loaded: Loaded }) {
  const { saved, confirming } = state;
  const fields = confirming ? state.candidate(confirming) : null;
  const { stats, documents } = loaded;
  const larger =
    fields !== null &&
    fields.chunk_tokens - fields.overlap_tokens > saved.chunk_tokens - saved.overlap_tokens;
  const close = () => state.setConfirming(null);

  return (
    <Modal
      open={confirming !== null}
      title="Embed every document again?"
      okText="Embed again"
      cancelText="Cancel"
      onOk={() => (confirming ? state.save(confirming, true) : undefined)}
      onCancel={close}
      onClose={close}
    >
      {fields ? (
        <div className={styles.modal}>
          {chunksChanged(saved, fields) ? (
            <>
              <p>
                Chunk size {saved.chunk_tokens} to {fields.chunk_tokens} tokens, overlap{" "}
                {saved.overlap_tokens} to {fields.overlap_tokens} tokens.
              </p>
              <p>
                {stats ? (
                  <>
                    The index now has {formatNumber(stats.chunk_count)} chunks. With the new values
                    it gets about{" "}
                    <strong>
                      {formatNumber(estimateChunks(stats.chunk_count, saved, fields))}
                    </strong>
                    .{" "}
                  </>
                ) : null}
                {larger
                  ? "Larger chunks, so the index gets fewer chunks: each chunk keeps more context, but search is less precise and each answer uses more input."
                  : "Smaller chunks, so the index gets more chunks: search is more precise and citations are tighter, but a fact can be split between chunks."}
              </p>
            </>
          ) : null}
          {fields.embedding_model !== saved.embedding_model ? (
            <p>
              Embedding model {saved.embedding_model} to <strong>{fields.embedding_model}</strong>.
              Search compares a question only with vectors of the same model, so{" "}
              <strong>
                chat cannot answer any question until every document is embedded again
              </strong>
              . The price per token of the new model can differ.
            </p>
          ) : null}
          <p>
            {documents === null ? "All" : `All ${formatNumber(documents)}`} documents are parsed and
            embedded again, one after the other.
            {stats
              ? ` This uses about ${formatNumber(stats.token_count)} embedding tokens and takes several minutes.`
              : " This takes several minutes."}{" "}
            Chat cannot answer about a document while it is embedded again.
          </p>
        </div>
      ) : null}
    </Modal>
  );
}
