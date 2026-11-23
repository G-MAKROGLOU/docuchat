"""Runs against a real Postgres when TEST_DATABASE_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid

import pytest

from app.domain.documents import Document
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.migrations import apply_migrations
from tests.support.db import DirectConnections
from tests.support.factories import make_document

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def test_migrations_are_idempotent_and_repository_round_trips() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    assert apply_migrations(conninfo) == []

    repository = PostgresDocumentRepository(DirectConnections(conninfo))
    sha = uuid.uuid4().hex * 2
    doc = make_document(
        source_id=f"set-{sha[:8]}", sha=sha, storage_key=f"documents/x/{sha}.pdf", size_bytes=123
    )

    async def scenario() -> None:
        await repository.add(doc)
        assert await repository.get(doc.id) == doc
        assert await repository.find_by_sha256(sha) == doc
        assert await repository.find_by_source_id(doc.source_id) == doc
        assert await repository.get(uuid.uuid4()) is None

    asyncio.run(scenario())


def test_search_filters_orders_and_counts() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    repository = PostgresDocumentRepository(DirectConnections(conninfo))
    # A unique marker keeps the search apart from rows of other tests.
    marker = uuid.uuid4().hex[:8]

    def make(brand: str, generic: str) -> Document:
        sha = uuid.uuid4().hex * 2
        return make_document(
            brand,
            generic,
            source_id=f"set-{sha[:8]}",
            sha=sha,
            storage_key=f"documents/x/{sha}.pdf",
            size_bytes=123,
        )

    zeta = make(f"Zeta{marker}", "zetamab")
    alpha = make("", f"alpha{marker}")
    beta = make(f"BETA{marker}", "betanol")

    async def scenario() -> None:
        for doc in (zeta, alpha, beta):
            await repository.add(doc)
        everything = await repository.search(marker, limit=10, offset=0)
        assert everything.items == [alpha, beta, zeta]
        assert everything.total == 3
        second = await repository.search(marker.upper(), limit=2, offset=2)
        assert second.items == [zeta]
        assert second.total == 3
        # LIKE wildcards in the query match only themselves.
        assert (await repository.search(f"%{marker}", limit=10, offset=0)).total == 0
        assert (await repository.search(f"_eta{marker}", limit=10, offset=0)).total == 0
        assert (await repository.search("", limit=1, offset=0)).total >= 3

    asyncio.run(scenario())
