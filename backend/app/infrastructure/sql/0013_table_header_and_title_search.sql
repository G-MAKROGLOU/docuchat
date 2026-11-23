-- The caption and header row of the table that a chunk continues; ingestion fills it.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS table_header text NOT NULL DEFAULT '';

-- BM25 also searches the section title ("8.2 Lactation"), with the same English stemming.
DROP INDEX IF EXISTS chunks_search_idx;
CREATE INDEX chunks_search_idx ON chunks
USING paradedb (
    id,
    (content::pdb.simple('stemmer=english')),
    (section_title::pdb.simple('stemmer=english')),
    document_id,
    (section_number::pdb.literal)
)
WITH (mutable_segment_rows = 0);
