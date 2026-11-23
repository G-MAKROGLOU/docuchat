"""Fakes for the corpus, ingestion, label queue, status and runtime settings ports."""

import re
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.application.ingestion import IngestionService
from app.application.ingestion_control import IngestionStatus
from app.domain.corpus_stats import CorpusStats
from app.domain.documents import Document, DocumentPage, DocumentStatus
from app.domain.entities import Chunk, LabelNode, TextSpan
from app.domain.label_queue import CatalogLabel, QueueEntry, QueueListing, QueueStatus
from app.domain.storage import label_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.support.factories import make_document
from tests.support.tuning import CHUNK_BYTES, INGEST

# ─────────────────── documents and sources ───────────────────

SPL = b'<?xml version="1.0"?><document xmlns="urn:hl7-org:v3"/>'


class FakeDocumentRepository:
    """An in-memory document repository with the full port."""

    def __init__(self, *documents: Document) -> None:
        self._by_id = {d.id: d for d in documents}

    async def add(self, document: Document) -> None:
        self._by_id[document.id] = document

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return self._by_id.get(document_id)

    async def find_by_source_id(self, source_id: str) -> Document | None:
        return next((d for d in self._by_id.values() if d.source_id == source_id), None)

    async def find_by_sha256(self, sha256: str) -> Document | None:
        return next((d for d in self._by_id.values() if d.sha256 == sha256), None)

    async def list_all(self) -> list[Document]:
        return list(self._by_id.values())

    async def known_source_ids(self, source_ids: list[str]) -> set[str]:
        return {d.source_id for d in self._by_id.values()} & set(source_ids)

    async def search(self, query: str, limit: int, offset: int) -> DocumentPage:
        needle = query.casefold()
        matches = sorted(
            (
                d
                for d in self._by_id.values()
                if needle in d.brand_name.casefold() or needle in d.generic_name.casefold()
            ),
            key=lambda d: ((d.brand_name or d.generic_name).casefold(), str(d.id)),
        )
        return DocumentPage(items=matches[offset : offset + limit], total=len(matches))

    async def replace_content(
        self, document_id: uuid.UUID, storage_key: str, sha256: str, size_bytes: int
    ) -> None:
        self._by_id[document_id] = replace(
            self._by_id[document_id],
            storage_key=storage_key,
            sha256=sha256,
            size_bytes=size_bytes,
            status=DocumentStatus.STORED,
            page_count=None,
        )

    async def update_ingestion(
        self,
        document_id: uuid.UUID,
        status: DocumentStatus,
        page_count: int | None = None,
        ingested_at: datetime | None = None,
        *,
        failure_reason: str | None = None,
        dosage_form: str | None = None,
    ) -> None:
        self._by_id[document_id] = replace(
            self._by_id[document_id],
            status=status,
            page_count=page_count,
            ingested_at=ingested_at,
            failure_reason=failure_reason,
        )


class SingleDocumentRepository:
    """Holds one document and records each status; a missing page count keeps the old one."""

    def __init__(self, document: Document) -> None:
        self.document = document
        self.statuses: list[DocumentStatus] = []

    async def update_ingestion(
        self,
        document_id: uuid.UUID,
        status: DocumentStatus,
        page_count: int | None = None,
        ingested_at: datetime | None = None,
        *,
        failure_reason: str | None = None,
        dosage_form: str | None = None,
    ) -> None:
        self.statuses.append(status)
        self.document = replace(
            self.document,
            status=status,
            page_count=page_count or self.document.page_count,
            ingested_at=ingested_at or self.document.ingested_at,
            failure_reason=failure_reason,
        )


class FakeSource:
    def __init__(
        self, payloads: dict[str, bytes] | None = None, labels: dict[str, bytes] | None = None
    ) -> None:
        self.calls: list[str] = []
        self._payloads = payloads or {}
        self._labels = labels or {}

    def fetch_pdf(self, source_id: str) -> bytes:
        self.calls.append(source_id)
        if source_id == "broken":
            raise OSError("network down")
        return self._payloads.get(source_id, b"%PDF-1.7 " + source_id.encode())

    def fetch_label(self, source_id: str) -> bytes:
        self.calls.append(f"{source_id}.xml")
        return self._labels.get(source_id, SPL)


class ListedDocuments:
    """Only lists documents: one per source ID, with a new ID on each call."""

    def __init__(self, *source_ids: str) -> None:
        self._source_ids = source_ids or ("a", "b")

    async def list_all(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(id=uuid.uuid4(), source_id=s) for s in self._source_ids]


class FakeTracker:
    def __init__(self, *, stale: bool) -> None:
        self._stale = stale
        self.marked = 0

    async def stale(self) -> bool:
        return self._stale

    async def mark_embedded(self) -> None:
        self.marked += 1


# ─────────────────── ingestion pipeline ───────────────────

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


class SentenceSplitter:
    """Fake splitter: one span per sentence, with its start offset."""

    def split(self, text: str) -> list[TextSpan]:
        return [
            TextSpan(start=m.start() + len(m[0]) - len(m[0].lstrip()), text=m[0].strip())
            for m in re.finditer(r"[^.]+\.?", text)
            if m[0].strip()
        ]


class WordCounter:
    def count(self, text: str) -> int:
        return len(text.split())


class FakeChunkRepository:
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

    def dosage_form(self, data: bytes) -> str:
        return "TABLET"


class FakeEmbedder:
    """Records the document texts; each vector holds the text length."""

    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return [[float(len(t)), 0.0] for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0, 0.0]


class QueryEmbedder:
    """Records the queries; every vector is [0.0]."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.0]


def stored_label_document(
    tmp_path: Path,
) -> tuple[SingleDocumentRepository, FileSystemDocumentStore]:
    """A stored document with its PDF and label in a file store."""
    document = make_document(
        "Lipitor", "atorvastatin", manufacturer="M", source_id="s1", size_bytes=10
    )
    store = FileSystemDocumentStore(tmp_path, CHUNK_BYTES)
    store.put(document.storage_key, b"%PDF-1.7 test", "application/pdf")
    store.put(label_key(document.id), b"<document/>", "application/xml")
    return SingleDocumentRepository(document), store


def ingestion_service(
    documents: SingleDocumentRepository,
    store: FileSystemDocumentStore,
    chunks: FakeChunkRepository,
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
        limits=INGEST,
    )


# ─────────────────── label queue ───────────────────

KNOWN_SET_ID = "a60cc18b-0631-4cf0-b021-9f52224ece65"
QUEUED_AT = datetime(2026, 11, 21, tzinfo=UTC)
CATALOG_LABEL = CatalogLabel(
    set_id=KNOWN_SET_ID, title="LIPITOR [VIATRIS]", version=8, published="Jul 15, 2026"
)


class FakeCatalog:
    def lookup(self, set_id: str) -> CatalogLabel | None:
        return CATALOG_LABEL if set_id == KNOWN_SET_ID else None

    def search(self, drug_name: str, limit: int) -> list[CatalogLabel]:
        return [CATALOG_LABEL][:limit]


class FakeQueue:
    def __init__(self) -> None:
        self.entries: dict[str, QueueEntry] = {}

    async def add(self, set_id: str, title: str) -> bool:
        old = self.entries.get(set_id)
        if old is not None and old.status is not QueueStatus.FAILED:
            return False
        self.entries[set_id] = QueueEntry(set_id, title, QueueStatus.QUEUED, None, QUEUED_AT)
        return True

    async def list_page(self, page: int, page_size: int) -> QueueListing:
        entries = sorted(self.entries.values(), key=lambda e: e.status is QueueStatus.ADDED)
        count = {s: sum(e.status is s for e in entries) for s in QueueStatus}
        start = (page - 1) * page_size
        return QueueListing(
            entries[start : start + page_size],
            count[QueueStatus.QUEUED],
            count[QueueStatus.ADDED],
            count[QueueStatus.FAILED],
        )

    async def next_queued(self, limit: int) -> list[QueueEntry]:
        queued = [e for e in self.entries.values() if e.status is QueueStatus.QUEUED]
        return queued[:limit]

    async def mark(self, set_id: str, status: QueueStatus, failure_reason: str | None) -> None:
        old = self.entries[set_id]
        self.entries[set_id] = QueueEntry(set_id, old.title, status, failure_reason, QUEUED_AT)

    async def known(self, set_ids: Sequence[str]) -> set[str]:
        return {s for s in set_ids if s in self.entries}

    async def remove(self, set_id: str) -> bool:
        entry = self.entries.get(set_id)
        if entry is None or entry.status is QueueStatus.ADDED:
            return False
        del self.entries[set_id]
        return True


# ─────────────────── status, control and runtime settings ───────────────────


class FakeCorpusStats:
    async def stats(self) -> CorpusStats:
        return CorpusStats(chunk_count=3864, token_count=1066576, embedding_models=["m1"])

    async def document_counts(self) -> dict[str, int]:
        return {"ingested": 48, "failed": 2}


class IdleControl:
    """No constructor arguments, so it works as a FastAPI dependency override."""

    async def status(self) -> IngestionStatus:
        return IngestionStatus(running=False, phase="idle", next_run_at=None)


class StubIngestionControl:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.started = 0

    async def status(self) -> SimpleNamespace:
        return SimpleNamespace(running=self.running, phase="idle", next_run_at=None)

    async def request(self) -> bool:
        if self.running:
            return False
        self.started += 1
        self.running = True
        return True


class FakeRuntimeSettingsRepository:
    def __init__(self, saved: dict[str, object] | None = None) -> None:
        self.saved = saved or {}

    async def load(self) -> dict[str, object]:
        return dict(self.saved)

    async def save(self, values: dict[str, object]) -> None:
        self.saved = dict(values)
