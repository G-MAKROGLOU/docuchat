# Ingestion

`IngestionService.ingest()` takes the sections from the SPL XML and the page numbers from the PDF, then writes embedded chunks. `python -m app.ingest --quick|--all [--force]` runs it for each stored document.

```mermaid
flowchart TD
    start(["ingest(document, force)"]) --> skipq{"not force<br/>and status = ingested<br/>and chunk embedding models = {EMBEDDING_MODEL}?"}
    skipq -->|yes| skipped(["IngestResult skipped=True"])
    skipq -->|no| ingesting["documents.update_ingestion(status=ingesting)"]

    ingesting --> read["Read both objects in parallel from DocumentStore<br/>PDF: document.storage_key<br/>SPL XML: label_key(document.id)"]

    read --> pdfpath["PyMuPdfParser.page_texts(PDF)<br/>one text per page"]
    read --> xmlpath["SplXmlParser.sections(XML)<br/>LabelNode tree of structuredBody"]

    xmlpath --> split["label_sections.split_sections(nodes)<br/>boxed warning 34066-1 as BW<br/>numbered titles 1 to 17, subsections by title number<br/>skip highlights, patient guides, package label"]
    split --> nosec{"any section?"}
    nosec -->|no| fail
    pdfpath --> locator["PageLocator(pages)<br/>normalized text a-z0-9<br/>cursor starts at FULL PRESCRIBING INFORMATION body"]

    nosec -->|yes| build["chunking.build_chunks(document, sections, splitter, counter, locator.locate)"]
    locator --> build

    subgraph perchunk["for each section, for each span"]
        span["SentenceTokenSplitter.split(section.text)<br/>500 tokens, 50 overlap, cl100k_base"]
        locate["locator.locate(content)<br/>match first and last 40 chars<br/>miss: current page, misses += 1"]
        draft["Chunk draft<br/>drug_name, section_number, section_title,<br/>page_start, page_end, anchor (8 words),<br/>token_count (TiktokenCounter)"]
        span --> locate --> draft
    end
    build --> perchunk

    perchunk --> empty{"any chunk?"}
    empty -->|no| fail
    empty -->|yes| inputs["embedding_input() per chunk<br/>EMBEDDING_PREFIX on: 'Drug: brand (generic). Section: n title.' + content"]
    inputs --> embed["OpenRouterEmbedder.embed_documents(inputs)<br/>batches of 100, size check = EMBEDDING_DIMENSIONS"]
    embed --> replace["PostgresChunkRepository.replace_for_document()<br/>one transaction: DELETE old chunks, INSERT new chunks"]
    replace --> done["documents.update_ingestion(status=ingested,<br/>page_count = number of PDF pages, ingested_at = now)"]
    done --> ok(["IngestResult chunks, tokens"])

    fail["any exception:<br/>log, update_ingestion(status=failed)"] --> failed(["IngestResult error"])
```

Document status values: `stored` (after download), `ingesting`, `ingested`, `failed`.
