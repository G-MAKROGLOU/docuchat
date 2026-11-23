"""Postgres adapter for DocumentRepository."""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

from app.domain.documents import Document, DocumentPage, DocumentStatus
from app.infrastructure.database import Connections
from app.infrastructure.document_locks import LOCK_KEY_SQL

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
    "failure_reason",
)
_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, _FIELDS))


# Empty query matches all rows; otherwise a substring match on either name.
_SEARCH_FILTER = sql.SQL(
    "%(query)s = '' OR brand_name ILIKE %(pattern)s OR generic_name ILIKE %(pattern)s"
)
_TITLE_ORDER = sql.SQL("lower(COALESCE(NULLIF(brand_name, ''), generic_name)), id")


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _to_document(row: dict[str, Any]) -> Document:
    return Document(**{**row, "status": DocumentStatus(row["status"])})


class PostgresDocumentRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def _one(self, where: str, value: object) -> Document | None:
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            query = sql.SQL("SELECT {} FROM documents WHERE {} = %s").format(
                _COLUMNS, sql.Identifier(where)
            )
            await cursor.execute(query, (value,))
            row = await cursor.fetchone()
        return _to_document(row) if row else None

    async def add(self, document: Document) -> None:
        async with self._connections.connection() as conn:
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
                    document.failure_reason,
                ),
            )

    async def get(self, document_id: UUID) -> Document | None:
        return await self._one("id", document_id)

    async def find_by_source_id(self, source_id: str) -> Document | None:
        return await self._one("source_id", source_id)

    async def find_by_sha256(self, sha256: str) -> Document | None:
        return await self._one("sha256", sha256)

    async def list_all(self) -> list[Document]:
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                sql.SQL("SELECT {} FROM documents ORDER BY brand_name, generic_name").format(
                    _COLUMNS
                )
            )
            return [_to_document(row) for row in await cursor.fetchall()]

    async def known_source_ids(self, source_ids: list[str]) -> set[str]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT source_id FROM documents WHERE source_id = ANY(%s)", (source_ids,)
            )
            return {str(row[0]) for row in await cursor.fetchall()}

    async def ingested_version(self) -> tuple[int, datetime | None]:
        """Changes when a label is ingested, re-ingested or removed: count and last ingest."""
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT count(*), max(ingested_at) FROM documents WHERE status = 'ingested'"
            )
            row = await cursor.fetchone()
        return (row[0], row[1]) if row else (0, None)

    async def reset_interrupted(self) -> int:
        """Sets documents left in "ingesting" by a crash back to "stored", so the next pass
        ingests them. A document whose lock another process holds is being ingested now."""
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "UPDATE documents SET status = 'stored' WHERE status = 'ingesting' "  # noqa: S608  # nosec B608  # a constant of this package
                "AND pg_try_advisory_xact_lock(" + LOCK_KEY_SQL + ")"
            )
            return cursor.rowcount

    async def search(self, query: str, limit: int, offset: int) -> DocumentPage:
        params = {
            "query": query,
            "pattern": _like_pattern(query),
            "limit": limit,
            "offset": offset,
        }
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                sql.SQL("SELECT count(*) AS total FROM documents WHERE {}").format(_SEARCH_FILTER),
                params,
            )
            count_row = await cursor.fetchone()
            await cursor.execute(
                sql.SQL(
                    "SELECT {} FROM documents WHERE {} ORDER BY {} "
                    "LIMIT %(limit)s OFFSET %(offset)s"
                ).format(_COLUMNS, _SEARCH_FILTER, _TITLE_ORDER),
                params,
            )
            rows = await cursor.fetchall()
        total = count_row["total"] if count_row else 0
        return DocumentPage(items=[_to_document(row) for row in rows], total=total)

    async def replace_content(
        self, document_id: UUID, storage_key: str, sha256: str, size_bytes: int
    ) -> None:
        async with self._connections.connection() as conn:
            await conn.execute(
                "UPDATE documents SET storage_key = %s, sha256 = %s, size_bytes = %s, "
                "status = 'stored', page_count = NULL, failure_reason = NULL WHERE id = %s",
                (storage_key, sha256, size_bytes, document_id),
            )

    async def update_ingestion(
        self,
        document_id: UUID,
        status: DocumentStatus,
        page_count: int | None = None,
        ingested_at: datetime | None = None,
        failure_reason: str | None = None,
    ) -> None:
        async with self._connections.connection() as conn:
            await conn.execute(
                "UPDATE documents SET status = %s, failure_reason = %s, "
                "page_count = COALESCE(%s, page_count), ingested_at = COALESCE(%s, ingested_at) "
                "WHERE id = %s",
                (status.value, failure_reason, page_count, ingested_at, document_id),
            )
