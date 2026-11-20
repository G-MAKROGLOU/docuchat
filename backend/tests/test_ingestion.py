import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.application.ingestion import IngestionService
from app.domain.documents import Document, DocumentStatus
from app.domain.entities import Chunk, PdfLine
from app.domain.storage import document_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.test_chunking import SentenceSplitter, WordCounter

LINES = [
    PdfLine(2, "FULL PRESCRIBING INFORMATION: CONTENTS*", bold=True),
    PdfLine(3, "FULL PRESCRIBING INFORMATION", bold=True),
    PdfLine(3, "1 INDICATIONS AND USAGE", bold=True),
    PdfLine(3, "Treats high cholesterol. Lowers stroke risk."),
    PdfLine(4, "2.1 Recommended Dosage", bold=True),
    PdfLine(4, "Take 10 mg once daily."),
]


class FakeDocuments:
    def __init__(self, document: Document) -> None:
        self.document = document
        self.statuses: list[DocumentStatus] = []

    async def update_ingestion(
        self,
        document_id: uuid.UUID,
        status: DocumentStatus,
        page_count: int | None = None,
        ingested_at: datetime | None = None,
    ) -> None:
        self.statuses.append(status)
        self.document = replace(
            self.document,
            status=status,
            page_count=page_count or self.document.page_count,
            ingested_at=ingested_at or self.document.ingested_at,
        )


class FakeChunks:
    def __init__(self) -> None:
        self.by_document: dict[uuid.UUID, list[Chunk]] = {}

    async def replace_for_document(self, document_id: uuid.UUID, chunks: Sequence[Chunk]) -> None:
        self.by_document[document_id] = list(chunks)

    async def embedding_models(self, document_id: uuid.UUID) -> set[str]:
        return {c.embedding_model or "" for c in self.by_document.get(document_id, [])}


class FakeParser:
    def __init__(self, lines: list[PdfLine]) -> None:
        self.lines = lines
        self.calls = 0

    def extract_lines(self, data: bytes) -> tuple[int, list[PdfLine]]:
        self.calls += 1
        return 4, self.lines


class FakeEmbedder:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return [[float(len(t)), 0.0] for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0, 0.0]


@pytest.fixture
def setup(tmp_path: Path) -> tuple[FakeDocuments, FileSystemDocumentStore]:
    doc_id = uuid.uuid4()
    document = Document(
        id=doc_id,
        brand_name="Lipitor",
        generic_name="atorvastatin",
        manufacturer="M",
        source_id="s1",
        storage_key=document_key(doc_id, "a" * 64),
        sha256="a" * 64,
        size_bytes=10,
        status=DocumentStatus.STORED,
    )
    store = FileSystemDocumentStore(tmp_path)
    store.put(document.storage_key, b"%PDF-1.7 test", "application/pdf")
    return FakeDocuments(document), store


def service(
    documents: FakeDocuments,
    store: FileSystemDocumentStore,
    chunks: FakeChunks,
    parser: FakeParser,
    embedder: FakeEmbedder,
    *,
    model: str = "openai/text-embedding-3-small",
) -> IngestionService:
    return IngestionService(
        store=store,
        documents=documents,
        chunks=chunks,
        parser=parser,
        splitter=SentenceSplitter(),
        counter=WordCounter(),
        embedder=embedder,
        embedding_model=model,
        embedding_prefix=True,
    )


def test_ingest_stores_embedded_chunks_and_marks_the_document(
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, embedder = FakeChunks(), FakeEmbedder()

    result = asyncio.run(
        service(documents, store, chunks, FakeParser(LINES), embedder).ingest(documents.document)
    )

    stored = chunks.by_document[documents.document.id]
    assert [(c.section_number, c.content) for c in stored] == [
        ("1", "Treats high cholesterol."),
        ("1", "Lowers stroke risk."),
        ("2.1", "Take 10 mg once daily."),
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
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, parser = FakeChunks(), FakeParser(LINES)
    ingestion = service(documents, store, chunks, parser, FakeEmbedder())
    asyncio.run(ingestion.ingest(documents.document))

    result = asyncio.run(ingestion.ingest(documents.document))

    assert result.skipped
    assert parser.calls == 1


def test_a_new_embedding_model_ingests_again(
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, parser = FakeChunks(), FakeParser(LINES)
    asyncio.run(
        service(documents, store, chunks, parser, FakeEmbedder()).ingest(documents.document)
    )

    result = asyncio.run(
        service(documents, store, chunks, parser, FakeEmbedder(), model="other/model").ingest(
            documents.document
        )
    )

    assert not result.skipped
    assert {c.embedding_model for c in chunks.by_document[documents.document.id]} == {"other/model"}


def test_a_parse_failure_marks_the_document_failed(
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    no_body = [PdfLine(1, "HIGHLIGHTS OF PRESCRIBING INFORMATION", bold=True)]

    result = asyncio.run(
        service(documents, store, FakeChunks(), FakeParser(no_body), FakeEmbedder()).ingest(
            documents.document
        )
    )

    assert result.error is not None
    assert documents.statuses == [DocumentStatus.INGESTING, DocumentStatus.FAILED]


def test_force_ingests_again(setup: tuple[FakeDocuments, FileSystemDocumentStore]) -> None:
    documents, store = setup
    parser = FakeParser(LINES)
    ingestion = service(documents, store, FakeChunks(), parser, FakeEmbedder())
    asyncio.run(ingestion.ingest(documents.document))

    result = asyncio.run(ingestion.ingest(documents.document, force=True))

    assert not result.skipped
    assert parser.calls == 2
