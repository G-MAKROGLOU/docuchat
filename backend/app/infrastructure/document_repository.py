"""Postgres adapter for DocumentRepository."""

from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.domain.documents import Document, DocumentStatus

_FIELDS = (
    "id",
    "brand_name",
    "generic_name",
    "manufacturer",
    "source_id",
    "storage_key",
    "sha256",
    "size_bytes",
    "page_count",
    "ingested_at",
    "status",
)
_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, _FIELDS))


def _to_document(row: dict[str, Any]) -> Document:
    return Document(**{**row, "status": DocumentStatus(row["status"])})


class PostgresDocumentRepository:
    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo

    async def _one(self, where: str, value: object) -> Document | None:
        async with await psycopg.AsyncConnection.connect(self._conninfo) as conn:
            cursor = conn.cursor(row_factory=dict_row)
            query = sql.SQL("SELECT {} FROM documents WHERE {} = %s").format(
                _COLUMNS, sql.Identifier(where)
            )
            await cursor.execute(query, (value,))
            row = await cursor.fetchone()
        return _to_document(row) if row else None

    async def add(self, document: Document) -> None:
        async with await psycopg.AsyncConnection.connect(self._conninfo) as conn:
            await conn.execute(
                sql.SQL("INSERT INTO documents ({}) VALUES ({})").format(
                    _COLUMNS, sql.SQL(", ").join(sql.Placeholder() * len(_FIELDS))
                ),
                (
                    document.id,
                    document.brand_name,
                    document.generic_name,
                    document.manufacturer,
                    document.source_id,
                    document.storage_key,
                    document.sha256,
                    document.size_bytes,
                    document.page_count,
                    document.ingested_at,
                    document.status.value,
                ),
            )

    async def get(self, document_id: UUID) -> Document | None:
        return await self._one("id", document_id)

    async def find_by_source_id(self, source_id: str) -> Document | None:
        return await self._one("source_id", source_id)

    async def find_by_sha256(self, sha256: str) -> Document | None:
        return await self._one("sha256", sha256)
