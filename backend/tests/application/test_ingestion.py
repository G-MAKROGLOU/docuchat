import asyncio
from pathlib import Path

import pytest

from app.domain.documents import DocumentStatus
from app.domain.storage import label_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.support.fakes_ingestion import (
    NODES,
    FakeChunkRepository,
    FakeEmbedder,
    FakeLabelParser,
    SingleDocumentRepository,
    ingestion_service,
    stored_label_document,
)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[SingleDocumentRepository, FileSystemDocumentStore]:
    return stored_label_document(tmp_path)


def test_ingest_stores_embedded_chunks_and_marks_the_document(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, embedder = FakeChunkRepository(), FakeEmbedder()

    result = asyncio.run(
        ingestion_service(documents, store, chunks, FakeLabelParser(NODES), embedder).ingest(
            documents.document
        )
    )

    stored = chunks.by_document[documents.document.id]
    assert [(c.section_number, c.content, c.page_start, c.page_end) for c in stored] == [
        ("1", "Treats high cholesterol.", 3, 3),
        ("1", "Lowers stroke risk.", 3, 3),
        ("2.1", "Take 10 mg once daily.", 4, 4),
    ]
    assert all(c.embedding and c.embedding_model == "openai/text-embedding-3-small" for c in stored)
    assert embedder.inputs[2] == (
        "Drug: Lipitor (atorvastatin). Section: 2.1 Recommended Dosage.\nTake 10 mg once daily."
    )
    assert documents.statuses == [DocumentStatus.INGESTING, DocumentStatus.INGESTED]
    assert documents.document.page_count == 4
    assert documents.document.ingested_at is not None
    assert (result.skipped, result.chunks) == (False, 3)
    assert result.tokens == sum(len(t.split()) for t in embedder.inputs)


def test_second_ingest_of_the_same_document_does_nothing(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, parser = FakeChunkRepository(), FakeLabelParser(NODES)
    ingestion = ingestion_service(documents, store, chunks, parser, FakeEmbedder())
    asyncio.run(ingestion.ingest(documents.document))

    result = asyncio.run(ingestion.ingest(documents.document))

    assert result.skipped
    assert parser.calls == 1


def test_a_new_embedding_model_ingests_again(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, parser = FakeChunkRepository(), FakeLabelParser(NODES)
    asyncio.run(
        ingestion_service(documents, store, chunks, parser, FakeEmbedder()).ingest(
            documents.document
        )
    )

    result = asyncio.run(
        ingestion_service(
            documents, store, chunks, parser, FakeEmbedder(), model="other/model"
        ).ingest(documents.document)
    )

    assert not result.skipped
    assert {c.embedding_model for c in chunks.by_document[documents.document.id]} == {"other/model"}


def test_a_parse_failure_marks_the_document_failed(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    no_body = [NODES[0]]

    result = asyncio.run(
        ingestion_service(
            documents, store, FakeChunkRepository(), FakeLabelParser(no_body), FakeEmbedder()
        ).ingest(documents.document)
    )

    assert result.error is not None
    assert documents.statuses == [DocumentStatus.INGESTING, DocumentStatus.FAILED]
    assert documents.document.failure_reason == result.error


def test_force_ingests_again(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    parser = FakeLabelParser(NODES)
    ingestion = ingestion_service(documents, store, FakeChunkRepository(), parser, FakeEmbedder())
    asyncio.run(ingestion.ingest(documents.document))

    result = asyncio.run(ingestion.ingest(documents.document, force=True))

    assert not result.skipped
    assert parser.calls == 2


def test_a_pdf_that_does_not_match_the_label_fails(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    other = [
        "FULL PRESCRIBING INFORMATION: CONTENTS",
        "FULL PRESCRIBING INFORMATION",
        "Other text.",
    ]

    result = asyncio.run(
        ingestion_service(
            documents,
            store,
            FakeChunkRepository(),
            FakeLabelParser(NODES),
            FakeEmbedder(),
            pages=other,
        ).ingest(documents.document)
    )

    assert result.error is not None
    assert "does not match" in result.error
    assert documents.statuses[-1] is DocumentStatus.FAILED


def test_a_missing_label_xml_fails_with_a_hint(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    store.delete(label_key(documents.document.id))

    result = asyncio.run(
        ingestion_service(
            documents, store, FakeChunkRepository(), FakeLabelParser(NODES), FakeEmbedder()
        ).ingest(documents.document)
    )

    assert result.error is not None
    assert "corpus download" in result.error
