# Ingestion

`IngestionService.ingest()` takes the sections from the SPL XML and the page numbers from the PDF, then writes embedded chunks. Only the ingest worker runs it, one pass at a time, with at most 4 documents at the same time (`INGEST_CONCURRENCY`).

## Passes: API, ingest worker and schedule

```mermaid
flowchart TD
    api["backend API<br/>POST /api/v1/ingestion<br/>PUT /api/v1/settings with a re-index"] -->|"IngestionControl.request()<br/>no new request while a pass runs or waits<br/>(POST answers 409)"| state[("ingestion_state, one row<br/>requested_at, force_requested,<br/>phase, next_run_at, heartbeat_at")]
    init["corpus-init: missing manifest labels<br/>into the label queue, then a request"] --> state
    boot["worker start: reset_interrupted()<br/>ingesting back to stored, then a request"] --> state
    sched["IngestionRunner schedule<br/>every 1 day from the worker start"] --> pass

    subgraph tick["IngestWorker.tick(), every 1 s"]
        refresh["refresh runtime settings<br/>new settings: new IngestionService"]
        take{"no pass running<br/>and a request in the row?"}
        report["report phase and next run;<br/>heartbeat_at = now"]
        refresh --> take
        take -->|no| report
    end
    state --> take
    take -->|"yes: take it"| pass
    report --> state

    subgraph pass["IngestionRunner._run(force)"]
        checking["phase checking<br/>check_for_updates(): fetch each SPL XML, 4 at a time<br/>changed: store PDF + XML, row back to stored"]
        downloading["phase downloading<br/>process_queue(): 50 queued labels per take,<br/>again until the queue is empty,<br/>through download_corpus()"]
        ingesting["phase ingesting<br/>force = force or chunk settings stale<br/>for each document in list_all():<br/>service.ingest(document, force), 4 at a time"]
        mark["force: mark_embedded()"]
        checking --> downloading --> ingesting --> mark
    end
```

`GET /api/v1/ready` reads the heartbeat: no report for 60 s means the worker is gone (an optional check, so the API stays ready). `GET /api/v1/status` shows the phase only while the heartbeat is current. The worker serves its metrics on port 9100.

## One document: ingest(document, force)

```mermaid
flowchart TD
    start(["ingest(document, force)"]) --> lock{"PostgresDocumentLocks.hold()<br/>pg_try_advisory_lock on the document ID"}
    lock -->|"held elsewhere"| skipped
    lock -->|held| skipq{"not force<br/>and status = ingested<br/>and chunk embedding models = {EMBEDDING_MODEL}?"}
    skipq -->|yes| skipped(["IngestResult skipped=True"])
    skipq -->|no| ingesting["documents.update_ingestion(status=ingesting)"]

    ingesting --> read["worker thread: read both objects from DocumentStore<br/>PDF: document.storage_key<br/>SPL XML: label_key(document.id), missing: error"]

    read --> pdfpath["PyMuPdfParser.page_texts(PDF)<br/>one text per page"]
    read --> xmlpath["SplXmlParser.sections(XML)<br/>LabelNode tree of structuredBody"]
    read --> formpath["SplXmlParser.dosage_form(XML)<br/>for example 'TABLET, FILM COATED'"]

    xmlpath --> split["label_sections.split_sections(nodes)<br/>boxed warning 34066-1 as BW<br/>numbered titles 1 to 17, subsections by title number<br/>skip highlights, patient guides, package label<br/>no section: LabelFormatError"]
    pdfpath --> locator["PageLocator(pages)<br/>normalized text a-z0-9<br/>cursor starts at FULL PRESCRIBING INFORMATION body"]

    split --> build["chunking.build_chunks(document, sections, splitter, counter, locator.locate_all)"]
    locator --> build

    subgraph perchunk["for each section, for each span"]
        span["SentenceTokenSplitter.split(section.text)<br/>chunk_tokens 500, overlap 50 (runtime settings), cl100k_base"]
        header["table_context(section.text, span.start)<br/>chunk starts inside a table:<br/>the 'Table ...' caption and the header row it lacks"]
        locate["locate_all(contents)<br/>first chunk of a section: with its heading<br/>match the first 40 chars, then the last 40 chars<br/>within the chunk length plus 300<br/>no match: by lines and table cells between the neighbours<br/>still no match: misses += 1"]
        draft["Chunk draft<br/>drug_name, section_number, section_title,<br/>page_start, page_end, anchor (8 words),<br/>token_count (TiktokenCounter), table_header"]
        span --> header --> locate --> draft
    end
    build --> perchunk

    perchunk --> checks{"any chunk, and misses<br/>at most 20% of the chunks?"}
    checks -->|no| fail
    checks -->|yes| inputs["embedding_input() per chunk<br/>table_header first, then the chunk text<br/>EMBEDDING_PREFIX on: 'Drug: brand (generic). Section: n title.' first"]
    inputs --> embed["OpenRouterEmbedder.embed_documents(inputs)<br/>batches of 100, size check = EMBEDDING_DIMENSIONS<br/>no cache for document vectors"]
    embed --> replace["PostgresChunkRepository.replace_for_document()<br/>one transaction: DELETE old chunks, INSERT new chunks"]
    formpath --> done
    replace --> done["documents.update_ingestion(status=ingested,<br/>page_count = number of PDF pages, ingested_at = now,<br/>dosage_form)"]
    done --> ok(["IngestResult chunks, tokens"])

    fail["any exception:<br/>log, update_ingestion(status=failed, failure_reason)"] --> failed(["IngestResult error"])
```

Document status values: `stored` (after download or a label update), `ingesting`, `ingested`, `failed`. `failure_reason` holds the message of a `ValueError` from our own checks, else only the exception type.

The stored chunk text stays as in the label. `table_header` is a separate column, so the page lookup, the anchor and the PDF highlight use the label text only.
