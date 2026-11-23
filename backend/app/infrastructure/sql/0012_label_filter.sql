-- The dosage form tells products of one name apart (injection, tablet); ingestion fills it.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS dosage_form text NOT NULL DEFAULT '';

-- Searches filter by label (document_id), not by drug name: one name can cover several labels.
-- document_id is a BM25 field, so the filter runs inside the index before the top-k cut.
DROP INDEX IF EXISTS chunks_search_idx;
CREATE INDEX chunks_search_idx ON chunks
USING paradedb (
    id,
    (content::pdb.simple('stemmer=english')),
    document_id,
    (section_number::pdb.literal)
)
WITH (mutable_segment_rows = 0);

-- The drug name filter is gone; the vector search filters on chunks_document_id_idx.
DROP INDEX IF EXISTS chunks_drug_name_idx;
