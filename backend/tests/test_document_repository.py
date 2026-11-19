"""Runs against a real Postgres when TEST_DATABASE_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid

import pytest

from app.domain.documents import Document, DocumentStatus
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.migrations import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
)


def test_migrations_are_idempotent_and_repository_round_trips() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    assert apply_migrations(conninfo) == []

    repository = PostgresDocumentRepository(conninfo)
    sha = uuid.uuid4().hex * 2
    doc = Document(
        id=uuid.uuid4(),
        brand_name="Brand",
        generic_name="generic",
        manufacturer="Maker",
        source_id=f"set-{sha[:8]}",
        storage_key=f"documents/x/{sha}.pdf",
        sha256=sha,
        size_bytes=123,
        status=DocumentStatus.STORED,
    )

    async def scenario() -> None:
        await repository.add(doc)
        assert await repository.get(doc.id) == doc
        assert await repository.find_by_sha256(sha) == doc
        assert await repository.find_by_source_id(doc.source_id) == doc
        assert await repository.get(uuid.uuid4()) is None

    asyncio.run(scenario())
