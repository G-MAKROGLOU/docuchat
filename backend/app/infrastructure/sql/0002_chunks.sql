CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

-- The vector size matches EMBEDDING_DIMENSIONS (1536 for openai/text-embedding-3-small).
CREATE TABLE chunks (
    id              uuid PRIMARY KEY,
    document_id     uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    drug_name       text NOT NULL,
    section_number  text NOT NULL,
    section_title   text NOT NULL,
    page_start      integer NOT NULL CHECK (page_start > 0),
    page_end        integer NOT NULL CHECK (page_end >= page_start),
    content         text NOT NULL,
    anchor          text NOT NULL,
    embedding       vector(1536) NOT NULL,
    embedding_model text NOT NULL,
    token_count     integer NOT NULL CHECK (token_count > 0)
);

CREATE INDEX chunks_document_id_idx ON chunks (document_id);

CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

-- BM25 on content (English stemming). drug_name and section_number are literal filter fields.
CREATE INDEX chunks_search_idx ON chunks
USING paradedb (
    id,
    (content::pdb.simple('stemmer=english')),
    (drug_name::pdb.literal),
    (section_number::pdb.literal)
)
WITH (key_field = 'id');
