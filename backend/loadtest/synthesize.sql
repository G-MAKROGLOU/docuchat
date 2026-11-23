-- Load test only: clone the ingested labels into synthetic labels, so the library holds about
-- (copies + 1) times the real count. Text stays the same; each copy gets its own IDs, drug name
-- and slightly moved vectors (exact duplicates would distort the HNSW graph).
-- Run on a load test database only:  psql -v copies=39 -f synthesize.sql
-- Remove again:  DELETE FROM documents WHERE source_id LIKE 'synthetic-%';  (chunks cascade)
\timing on

CREATE TEMP TABLE synth AS
SELECT d.*, n, gen_random_uuid() AS new_id
FROM documents d
CROSS JOIN generate_series(1, :copies) AS n
WHERE d.status = 'ingested' AND d.source_id NOT LIKE 'synthetic-%';

INSERT INTO documents (
    id, brand_name, generic_name, manufacturer, source_id, storage_key, sha256,
    size_bytes, page_count, ingested_at, status
)
SELECT new_id, brand_name || ' Synth ' || n, generic_name || ' synth ' || n, manufacturer,
       'synthetic-' || n || '-' || source_id, storage_key,
       encode(sha256(convert_to(new_id::text, 'UTF8')), 'hex'),
       size_bytes, page_count, now(), 'ingested'
FROM synth;

INSERT INTO chunks (
    id, document_id, drug_name, section_number, section_title, page_start, page_end,
    content, anchor, embedding, embedding_model, token_count
)
SELECT gen_random_uuid(), s.new_id, c.drug_name || ' Synth ' || s.n, c.section_number,
       c.section_title, c.page_start, c.page_end, c.content, c.anchor,
       (SELECT array_agg(v + (random() - 0.5) * 0.02 ORDER BY i)
        FROM unnest(c.embedding::real[]) WITH ORDINALITY AS t(v, i))::vector,
       c.embedding_model, c.token_count
FROM chunks c
JOIN synth s ON s.id = c.document_id;

ANALYZE documents;
ANALYZE chunks;
SELECT count(*) AS documents FROM documents;
SELECT count(*) AS chunks FROM chunks;
