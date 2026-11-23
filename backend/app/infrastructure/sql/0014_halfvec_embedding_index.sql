-- HNSW on the half-precision cast of the embedding: half the index size of the full-precision
-- index. The vector search orders by the same expression (chunk_search.py). The table keeps
-- full-precision vectors. Build the new index first; the drop at the end locks only briefly.
CREATE INDEX IF NOT EXISTS chunks_embedding_half_idx ON chunks
USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops);

DROP INDEX IF EXISTS chunks_embedding_idx;
