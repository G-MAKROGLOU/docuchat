"""Runs against a real ParadeDB when TEST_DATABASE_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid

import psycopg
import pytest

from app.domain.documents import Document, DocumentStatus
from app.domain.entities import Chunk
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.migrations import apply_migrations
from tests.db import DirectConnections

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
)


def chunk(document_id: uuid.UUID, content: str, model: str = "m1") -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        document_id=document_id,
        drug_name="Testadol",
        section_number="2.1",
        section_title="Recommended Dosage",
        page_start=3,
        page_end=4,
        content=content,
        anchor=" ".join(content.split()[:8]),
        token_count=len(content.split()),
        embedding=tuple([0.01] * 1536),
        embedding_model=model,
    )


def test_replace_for_document_swaps_chunks_and_the_indexes_accept_them() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    sha = uuid.uuid4().hex * 2
    doc = Document(
        id=uuid.uuid4(),
        brand_name="Testadol",
        generic_name="testamine",
        manufacturer="M",
        source_id=f"chunk-test-{sha[:8]}",
        storage_key=f"documents/x/{sha}.pdf",
        sha256=sha,
        size_bytes=1,
        status=DocumentStatus.STORED,
    )
    repository = PostgresChunkRepository(DirectConnections(conninfo))

    async def scenario() -> None:
        await PostgresDocumentRepository(DirectConnections(conninfo)).add(doc)
        await repository.replace_for_document(doc.id, [chunk(doc.id, "Take 10 mg daily.")])
        await repository.replace_for_document(
            doc.id,
            [
                chunk(doc.id, "Take 20 mg zebrafinch daily.", "m2"),
                chunk(doc.id, "Swallow whole.", "m2"),
            ],
        )
        assert await repository.embedding_models(doc.id) == {"m2"}

    asyncio.run(scenario())

    with psycopg.connect(conninfo) as conn:
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = %s ORDER BY content", (doc.id,)
        ).fetchall()
        bm25 = conn.execute(
            "SELECT count(*) FROM chunks WHERE content ||| %s AND document_id = %s",
            ("zebrafinch", doc.id),
        ).fetchone()
    assert [r[0] for r in rows] == ["Swallow whole.", "Take 20 mg zebrafinch daily."]
    assert bm25 == (1,)
