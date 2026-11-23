# Data model

Tables from the one schema file `backend/app/infrastructure/sql/0001_schema.sql`, and the SeaweedFS objects from `backend/app/domain/storage.py`. `migrations.py` applies each SQL file once, in name order, at the start of the backend, the ingest worker and corpus-init. It records each applied file in `schema_migrations`.

## Library

```mermaid
erDiagram
    documents ||--o{ chunks : "document_id, ON DELETE CASCADE"
    documents ||--|| PDF_OBJECT : "storage_key"
    documents ||--o| LABEL_OBJECT : "label_key(id)"
    label_queue |o..o| documents : "set_id = source_id, no foreign key"

    documents {
        uuid id PK
        text brand_name "NOT NULL"
        text generic_name "NOT NULL"
        text manufacturer "NOT NULL"
        text source_id "NOT NULL, DailyMed set ID, index documents_source_id_idx"
        text storage_key "NOT NULL"
        char_64 sha256 UK "char(64) NOT NULL UNIQUE"
        bigint size_bytes "NOT NULL, CHECK > 0"
        integer page_count "NULL, CHECK > 0"
        timestamptz ingested_at "NULL"
        text status "stored | ingesting | ingested | failed"
        text failure_reason "NULL"
        text dosage_form "NOT NULL DEFAULT empty, SPL formCode"
    }

    chunks {
        uuid id PK "BM25 key (first index column)"
        uuid document_id FK "NOT NULL, BM25 field, index chunks_document_id_idx"
        text drug_name "NOT NULL"
        text section_number "NOT NULL, BM25 literal field"
        text section_title "NOT NULL, BM25 stemmer=english"
        integer page_start "NOT NULL, CHECK > 0"
        integer page_end "NOT NULL, CHECK >= page_start"
        text content "NOT NULL, BM25 stemmer=english"
        text anchor "NOT NULL, first 8 words"
        vector_1536 embedding "vector(1536) NOT NULL, HNSW on the halfvec(1536) cast"
        text embedding_model "NOT NULL"
        integer token_count "NOT NULL, CHECK > 0"
        text table_header "NOT NULL DEFAULT empty, table caption and header row"
    }

    label_queue {
        text set_id PK "DailyMed set ID"
        text title "NOT NULL"
        text status "queued | added | failed"
        text failure_reason "NULL"
        timestamptz created_at "NOT NULL DEFAULT now()"
    }

    PDF_OBJECT {
        string key "documents/{document_id}/{sha256}.pdf"
        string content_type "application/pdf"
    }

    LABEL_OBJECT {
        string key "documents/{document_id}/label.xml"
        string content_type "application/xml (SPL XML)"
    }
```

`PDF_OBJECT` and `LABEL_OBJECT` are S3 objects in the `S3_BUCKET` bucket, not tables. A label update stores a new PDF under a new key, updates `storage_key`, `sha256` and `size_bytes`, then deletes the old PDF object.

## Conversations, settings and worker state

```mermaid
erDiagram
    conversations ||--o{ conversation_turns : "conversation_id, ON DELETE CASCADE"

    conversations {
        uuid id PK
        timestamptz created_at "NOT NULL DEFAULT now()"
    }

    conversation_turns {
        uuid id PK
        uuid conversation_id FK "NOT NULL"
        text role "user | assistant"
        text text "NOT NULL"
        text_array citations "text[] NOT NULL DEFAULT empty"
        timestamptz created_at "NOT NULL DEFAULT clock_timestamp()"
    }

    runtime_settings {
        text key PK "one saved setting, or embedded_index"
        jsonb value "NOT NULL"
    }

    ingestion_state {
        smallint id PK "CHECK id = 1, one row"
        text phase "idle | checking | downloading | ingesting"
        timestamptz requested_at "NULL, a pass is asked for"
        boolean force_requested "NOT NULL DEFAULT false"
        timestamptz next_run_at "NULL"
        timestamptz heartbeat_at "NULL, last worker report"
    }

    schema_migrations {
        text version PK "file stem: 0001_schema"
        timestamptz applied_at "NOT NULL DEFAULT now()"
    }
```

`DELETE /api/v1/conversations/{id}` deletes a conversation; its turns go with it. The frontend sends it when the page unloads (`pagehide`).

## Indexes

| Index | Table | Type | Definition |
|---|---|---|---|
| `chunks_embedding_half_idx` | `chunks` | HNSW (pgvector) | `(embedding::halfvec(1536)) halfvec_cosine_ops`; half the size of a full-precision index; the query sets `hnsw.ef_search` to `SEARCH_HNSW_EF_SEARCH` (at least 2 times the limit) |
| `chunks_search_idx` | `chunks` | BM25 (pg_search, `USING paradedb`) | `id`, `content::pdb.simple('stemmer=english')`, `section_title::pdb.simple('stemmer=english')`, `document_id`, `section_number::pdb.literal`; `WITH (mutable_segment_rows = 0)` |
| `chunks_document_id_idx` | `chunks` | B-tree | `document_id` |
| `documents_source_id_idx` | `documents` | B-tree | `source_id` |
| `conversation_turns_conversation_idx` | `conversation_turns` | B-tree | `conversation_id, created_at` |

`chunks.drug_name` is still stored and sent to the model, but no index and no search filter use it now.
