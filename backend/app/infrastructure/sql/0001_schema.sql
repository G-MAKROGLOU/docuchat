-- The whole schema. The ingest worker, the API and corpus-init apply it once (schema_migrations).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;
-- The ParadeDB image installs these in every new database. Nothing here uses them: drug names
-- are matched in Python, and there is no geodata. Dependents first.
DROP EXTENSION IF EXISTS postgis_tiger_geocoder;
DROP EXTENSION IF EXISTS postgis_topology;
DROP EXTENSION IF EXISTS postgis;
DROP EXTENSION IF EXISTS fuzzystrmatch;
DROP EXTENSION IF EXISTS pg_ivm;

-- One row per stored label. dosage_form tells products of one name apart (injection, tablet).
CREATE TABLE documents (
    id             uuid PRIMARY KEY,
    brand_name     text NOT NULL,
    generic_name   text NOT NULL,
    manufacturer   text NOT NULL,
    source_id      text NOT NULL,
    storage_key    text NOT NULL,
    sha256         char(64) NOT NULL UNIQUE,
    size_bytes     bigint NOT NULL CHECK (size_bytes > 0),
    page_count     integer CHECK (page_count > 0),
    ingested_at    timestamptz,
    status         text NOT NULL CHECK (status IN ('stored', 'ingesting', 'ingested', 'failed')),
    failure_reason text,
    dosage_form    text NOT NULL DEFAULT ''
);

CREATE INDEX documents_source_id_idx ON documents (source_id);

-- The vector size matches EMBEDDING_DIMENSIONS (1536 for openai/text-embedding-3-small).
-- table_header: the caption and header row of the table that a chunk continues.
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
    token_count     integer NOT NULL CHECK (token_count > 0),
    table_header    text NOT NULL DEFAULT ''
);

-- The vector search filters by label on this index.
CREATE INDEX chunks_document_id_idx ON chunks (document_id);

-- HNSW on the half-precision cast: half the index size of a full-precision index, the same
-- recall (docs/agent-log.md). The vector search orders by the same expression.
CREATE INDEX chunks_embedding_half_idx ON chunks
USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops);

-- BM25 on the content and the section title (English stemming). Searches filter by label
-- (document_id) inside the index, before the top-k cut. The first column, id, is the key.
-- No mutable segment: its rows are read on every search (58 ms per query at 1000 rows), and
-- ingestion writes in batches.
CREATE INDEX chunks_search_idx ON chunks
USING paradedb (
    id,
    (content::pdb.simple('stemmer=english')),
    (section_title::pdb.simple('stemmer=english')),
    document_id,
    (section_number::pdb.literal)
)
WITH (mutable_segment_rows = 0);

CREATE TABLE conversations (
    id          uuid PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE conversation_turns (
    id               uuid PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             text NOT NULL CHECK (role IN ('user', 'assistant')),
    text             text NOT NULL,
    citations        text[] NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX conversation_turns_conversation_idx ON conversation_turns (conversation_id, created_at);

CREATE TABLE label_queue (
    set_id         text PRIMARY KEY,
    title          text NOT NULL,
    status         text NOT NULL CHECK (status IN ('queued', 'added', 'failed')),
    failure_reason text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runtime_settings (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);

-- One row: the ingest worker reports here, and the API processes read it and ask for passes.
CREATE TABLE ingestion_state (
    id              smallint PRIMARY KEY CHECK (id = 1),
    phase           text NOT NULL DEFAULT 'idle'
                    CHECK (phase IN ('idle', 'checking', 'downloading', 'ingesting')),
    requested_at    timestamptz,
    force_requested boolean NOT NULL DEFAULT false,
    next_run_at     timestamptz,
    heartbeat_at    timestamptz
);

INSERT INTO ingestion_state (id) VALUES (1);
