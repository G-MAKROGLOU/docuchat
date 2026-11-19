CREATE TABLE documents (
    id            uuid PRIMARY KEY,
    brand_name    text NOT NULL,
    generic_name  text NOT NULL,
    manufacturer  text NOT NULL,
    source_id     text NOT NULL,
    storage_key   text NOT NULL,
    sha256        char(64) NOT NULL UNIQUE,
    size_bytes    bigint NOT NULL CHECK (size_bytes > 0),
    page_count    integer CHECK (page_count > 0),
    ingested_at   timestamptz,
    status        text NOT NULL CHECK (status IN ('stored', 'ingesting', 'ingested', 'failed'))
);

CREATE INDEX documents_source_id_idx ON documents (source_id);
