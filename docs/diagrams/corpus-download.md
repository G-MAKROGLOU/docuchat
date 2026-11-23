# Corpus download

`python -m app.corpus_download --quick|--all` stores the label PDF and the SPL XML of each manifest entry, then adds the document row. The run is idempotent by `source_id`. The manifest is `backend/corpus/manifest.json`, mounted at `/corpus/manifest.json`.

Other callers of `download_corpus()`: the one-shot `corpus-init` job runs `corpus_download.main(["--all"])`, then `ingest.main(["--all"])`, when a manifest label is not in the library. The label queue of the ingest worker (`label_queue.process_queue()`) calls it for one label at a time, with the SPL XML that it already fetched.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant CLI as corpus_download.main
    participant DL as corpus._Downloader
    participant Repo as PostgresDocumentRepository
    participant Src as DailyMedClient
    participant Store as DocumentStore (S3)

    Op->>CLI: --quick or --all [--manifest]
    CLI->>CLI: apply_migrations(DATABASE_URL)
    CLI->>CLI: parse_manifest(manifest.json, quick)
    CLI->>Src: create with pdf_url_template, label_url_template (https only)
    Note over Src: each GET: 3 tries with backoff 1 s, 2 s<br/>on 408, 429, 500, 502, 503, 504 and network errors<br/>response at most 50 MB
    CLI->>DL: download_corpus(entries, source, store, repository)

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

    DL-->>CLI: DownloadReport(downloaded, skipped, failed, bytes)
    CLI-->>Op: summary line, exit 1 if failed > 0
```
