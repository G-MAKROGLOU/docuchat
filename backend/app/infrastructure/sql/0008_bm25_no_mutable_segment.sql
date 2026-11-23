-- Rows in the mutable segment are read into memory on every search: up to 1000 buffered rows
-- cost about 58 ms per query. Ingestion writes in batches, so it does not need the buffer.
ALTER INDEX chunks_search_idx SET (mutable_segment_rows = 0);
-- Flushes the rows that are in the mutable segment now.
REINDEX INDEX chunks_search_idx;
