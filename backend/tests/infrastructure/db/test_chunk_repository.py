"""Runs against a real ParadeDB when TEST_DATABASE_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid

import psycopg
import pytest

from app.domain.entities import Chunk
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.corpus_stats_repository import PostgresCorpusStatsRepository
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.migrations import apply_migrations
from tests.support.db import DirectConnections
from tests.support.factories import make_chunk, make_document

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def chunk(document_id: uuid.UUID, content: str, model: str = "m1") -> Chunk:
    return make_chunk(
        content,
        document_id=document_id,
        drug="Testadol",
        section="2.1",
        title="Recommended Dosage",
        page_start=3,
        page_end=4,
        anchor=" ".join(content.split()[:8]),
        tokens=len(content.split()),
        embedding=tuple([0.01] * 1536),
        embedding_model=model,
    )


def test_replace_for_document_swaps_chunks_and_the_indexes_accept_them() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    sha = uuid.uuid4().hex * 2
    doc = make_document(
        "Testadol",
        "testamine",
        manufacturer="M",
        source_id=f"chunk-test-{sha[:8]}",
        sha=sha,
        storage_key=f"documents/x/{sha}.pdf",
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


def test_corpus_stats_totals_chunks_and_tokens() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    connections = DirectConnections(conninfo)
    stats = asyncio.run(PostgresCorpusStatsRepository(connections).stats())
    with psycopg.connect(conninfo) as conn:
        expected = conn.execute(
            "SELECT count(*), COALESCE(sum(token_count), 0) FROM chunks"
        ).fetchone()

    assert (stats.chunk_count, stats.token_count) == expected
    assert stats.embedding_models == sorted(stats.embedding_models)
