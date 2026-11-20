import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.application.ingestion import IngestionService
from app.domain.documents import Document, DocumentStatus
from app.domain.entities import Chunk, LabelNode
from app.domain.storage import document_key, label_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.test_chunking import SentenceSplitter, WordCounter

NODES = [
    LabelNode("48780-1", "Highlights", "Take 10 mg once daily."),
    LabelNode("34067-9", "1 INDICATIONS AND USAGE", "Treats high cholesterol. Lowers stroke risk."),
    LabelNode(
        "34068-7",
        "2 DOSAGE AND ADMINISTRATION",
        "",
        (LabelNode("42229-5", "2.1 Recommended Dosage", "Take 10 mg once daily."),),
    ),
]
PAGES = [
    "HIGHLIGHTS\nTake 10 mg once daily.",
    "FULL PRESCRIBING INFORMATION: CONTENTS*",
    "FULL PRESCRIBING INFORMATION\n1 INDICATIONS AND USAGE\nTreats high cholesterol.\n"
    "Lowers stroke risk.",
    "2 DOSAGE AND ADMINISTRATION\n2.1 Recommended Dosage\nTake 10 mg once daily.",
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


class FakePdfParser:
    def __init__(self, pages: list[str]) -> None:
        self.pages = pages

    def page_texts(self, data: bytes) -> list[str]:
        assert data.startswith(b"%PDF-")
        return self.pages


class FakeLabelParser:
    def __init__(self, nodes: list[LabelNode]) -> None:
        self.nodes = nodes
        self.calls = 0

    def sections(self, data: bytes) -> list[LabelNode]:
        assert data.startswith(b"<document")
        self.calls += 1
        return self.nodes


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
    store.put(label_key(doc_id), b"<document/>", "application/xml")
    return FakeDocuments(document), store


def service(
    documents: FakeDocuments,
    store: FileSystemDocumentStore,
    chunks: FakeChunks,
    parser: FakeLabelParser,
    embedder: FakeEmbedder,
    *,
    model: str = "openai/text-embedding-3-small",
    pages: list[str] = PAGES,
) -> IngestionService:
    return IngestionService(
        store=store,
        documents=documents,
        chunks=chunks,
        pdf_parser=FakePdfParser(pages),
        label_parser=parser,
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
        service(documents, store, chunks, FakeLabelParser(NODES), embedder).ingest(
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
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, parser = FakeChunks(), FakeLabelParser(NODES)
    ingestion = service(documents, store, chunks, parser, FakeEmbedder())
    asyncio.run(ingestion.ingest(documents.document))

    result = asyncio.run(ingestion.ingest(documents.document))

    assert result.skipped
    assert parser.calls == 1


def test_a_new_embedding_model_ingests_again(
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    chunks, parser = FakeChunks(), FakeLabelParser(NODES)
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
    no_body = [NODES[0]]

    result = asyncio.run(
        service(documents, store, FakeChunks(), FakeLabelParser(no_body), FakeEmbedder()).ingest(
            documents.document
        )
    )

    assert result.error is not None
    assert documents.statuses == [DocumentStatus.INGESTING, DocumentStatus.FAILED]


def test_force_ingests_again(setup: tuple[FakeDocuments, FileSystemDocumentStore]) -> None:
    documents, store = setup
    parser = FakeLabelParser(NODES)
    ingestion = service(documents, store, FakeChunks(), parser, FakeEmbedder())
    asyncio.run(ingestion.ingest(documents.document))

    result = asyncio.run(ingestion.ingest(documents.document, force=True))

    assert not result.skipped
    assert parser.calls == 2


def test_a_pdf_that_does_not_match_the_label_fails(
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    other = [
        "FULL PRESCRIBING INFORMATION: CONTENTS",
        "FULL PRESCRIBING INFORMATION",
        "Other text.",
    ]

    result = asyncio.run(
        service(
            documents, store, FakeChunks(), FakeLabelParser(NODES), FakeEmbedder(), pages=other
        ).ingest(documents.document)
    )

    assert result.error is not None
    assert "does not match" in result.error
    assert documents.statuses[-1] is DocumentStatus.FAILED


def test_a_missing_label_xml_fails_with_a_hint(
    setup: tuple[FakeDocuments, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    store.delete(label_key(documents.document.id))

    result = asyncio.run(
        service(documents, store, FakeChunks(), FakeLabelParser(NODES), FakeEmbedder()).ingest(
            documents.document
        )
    )

    assert result.error is not None
    assert "corpus download" in result.error
