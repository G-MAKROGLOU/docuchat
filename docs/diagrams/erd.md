# Data model

Tables from `backend/app/infrastructure/sql/0001_documents.sql` and `0002_chunks.sql`, and the SeaweedFS objects from `backend/app/domain/storage.py`. `migrations.py` records each applied file in `schema_migrations`.

```mermaid
erDiagram
    documents ||--o{ chunks : "document_id, ON DELETE CASCADE"
    documents ||--|| PDF_OBJECT : "storage_key"
    documents ||--o| LABEL_OBJECT : "label_key(id)"

    documents {
        uuid id PK
        text brand_name "NOT NULL"
        text generic_name "NOT NULL"
        text manufacturer "NOT NULL"
        text source_id "NOT NULL, index documents_source_id_idx"
        text storage_key "NOT NULL"
        char_64 sha256 UK "char(64) NOT NULL UNIQUE"
        bigint size_bytes "NOT NULL, CHECK > 0"
        integer page_count "NULL, CHECK > 0"
        timestamptz ingested_at "NULL"
        text status "stored | ingesting | ingested | failed"
    }

    chunks {
        uuid id PK "BM25 key_field"
        uuid document_id FK "NOT NULL, index chunks_document_id_idx"
        text drug_name "NOT NULL, BM25 literal field"
        text section_number "NOT NULL, BM25 literal field"
        text section_title "NOT NULL"
        integer page_start "NOT NULL, CHECK > 0"
        integer page_end "NOT NULL, CHECK >= page_start"
        text content "NOT NULL, BM25 simple tokenizer, stemmer=english"
        text anchor "NOT NULL, first 8 words"
        vector_1536 embedding "vector(1536) NOT NULL, HNSW vector_cosine_ops"
        text embedding_model "NOT NULL"
        integer token_count "NOT NULL, CHECK > 0"
    }

    schema_migrations {
        text version PK "file stem, for example 0002_chunks"
        timestamptz applied_at "NOT NULL DEFAULT now()"
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

Indexes on `chunks`:

| Index | Type | Definition |
|---|---|---|
| `chunks_embedding_idx` | HNSW (pgvector) | `embedding vector_cosine_ops` |
| `chunks_search_idx` | BM25 (pg_search, `USING paradedb`) | `id`, `content::pdb.simple('stemmer=english')`, `drug_name::pdb.literal`, `section_number::pdb.literal`, `key_field = 'id'` |
| `chunks_document_id_idx` | B-tree | `document_id` |

`PDF_OBJECT` and `LABEL_OBJECT` are S3 objects in the `S3_BUCKET` bucket, not tables.
