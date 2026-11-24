# Corpus download

The ingest worker is the only process that downloads labels. Labels come into the label queue from two places: the Corpus page (`POST /api/v1/labels`) and the one-shot `corpus-init` job. `download_corpus()` stores the label PDF and the SPL XML of a label, then adds the document row. It is idempotent by `source_id`.

## Fill the library: corpus-init and the label queue

`python -m app.worker.corpus_init` runs once per stack start. The manifest is `backend/corpus/manifest.json`, mounted at `/corpus/manifest.json`.

```mermaid
sequenceDiagram
    autonumber
    participant Init as corpus-init (queue_manifest)
    participant Docs as PostgresDocumentRepository
    participant Queue as PostgresLabelQueueRepository
    participant State as ingestion_state
    participant Worker as ingest worker (IngestionRunner)

    Init->>Init: check_schema (exit when not current), parse_manifest(manifest.json)
    Init->>Docs: known_source_ids(manifest set IDs)
    loop each manifest label not in the library
        Init->>Queue: add(set_id, brand or generic name)
        Note over Queue: new or failed entry: queued<br/>queued or added entry: unchanged
    end
    alt at least one label queued
        Init->>State: request(force=false)
    end
    Note over Init: exit 0
    Worker->>State: take() on the next tick, after a running pass
    loop phase downloading, until a take returns nothing
        Worker->>Queue: next_queued(50)
        Worker->>Worker: _take(entry): fetch SPL XML, check namespace,<br/>read names, download_corpus() with the fetched XML
        Worker->>Queue: mark(added or failed with a reason)
    end
    Note over Worker: phase ingesting: every document, 4 at a time
```

## One label: download_corpus()

```mermaid
sequenceDiagram
    autonumber
    participant Q as label_queue._take
    participant DL as corpus._Downloader
    participant Repo as PostgresDocumentRepository
    participant Src as DailyMedClient
    participant Store as DocumentStore (S3)

    Note over Src: each GET: 3 tries with backoff 1 s, 2 s<br/>on 408, 429, 500, 502, 503, 504 and network errors<br/>response at most 50 MB
    Q->>DL: download_corpus([entry], prefetched source, store, repository)

    loop each CorpusEntry, errors counted as failed
        DL->>Repo: find_by_source_id(source_id)
        alt row exists and PDF object exists
            DL->>Store: exists(label_key(id))
            alt label.xml exists
                Note over DL: skipped += 1
            else label.xml missing
                DL->>Src: fetch_label(source_id)
                Note over DL: sleep 0.3 s, check SPL namespace urn:hl7-org:v3
                DL->>Store: put(label_key(id), XML, application/xml)
                Note over DL: downloaded += 1
            end
        else no row, or row without PDF object
            DL->>Src: fetch_pdf(source_id)
            Note over DL: sleep 0.3 s, check %PDF- magic, compute sha256
            alt row exists (PDF object missing)
                Note over DL: sha256 must equal the stored sha256, else error
                DL->>Store: put(storage_key, PDF, application/pdf)
                DL->>Src: fetch_label(source_id)
                Note over DL: sleep 0.3 s, check SPL namespace
                DL->>Store: put(label_key(id), XML, application/xml)
                Note over DL: downloaded += 1
            else no row
                DL->>Repo: find_by_sha256(sha256)
                alt same PDF already stored
                    Note over DL: skipped += 1
                else new label
                    Note over DL: new uuid4, storage_key = document_key(id, sha256)
                    DL->>Src: fetch_label(source_id)
                    Note over DL: sleep 0.3 s, check SPL namespace<br/>objects first, row second
                    DL->>Store: put(storage_key, PDF, application/pdf)
                    DL->>Store: put(label_key(id), XML, application/xml)
                    DL->>Repo: add(Document status=stored)
                    Note over DL: downloaded += 1
                end
            end
        end
    end

    DL-->>Q: DownloadReport(downloaded, skipped, failed, bytes)
    Note over Q: no row for the set ID: failed, with the reason
```
