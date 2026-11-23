"""ChunkSearch adapter: pgvector HNSW (cosine) and ParadeDB BM25, with the same label filter."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

from app.domain.entities import Chunk
from app.infrastructure.chunk_repository import vector_literal
from app.infrastructure.database import Connections
from app.infrastructure.metrics import SEARCH_SECONDS

_FIELDS = (
    "id",
    "document_id",
    "drug_name",
    "section_number",
    "section_title",
    "page_start",
    "page_end",
    "content",
    "anchor",
    "token_count",
    "embedding_model",
    "table_header",
)
_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, _FIELDS))
# A title match counts half a content match. ASSUMED value, to tune on the golden set.
TITLE_BOOST = 0.5


def _filter(labels: Sequence[UUID]) -> tuple[sql.Composable, tuple[Any, ...]]:
    if not labels:
        return sql.SQL(""), ()
    return sql.SQL(" AND document_id = ANY(%s)"), (list(labels),)


class PostgresChunkSearch:
    def __init__(self, connections: Connections, embedding_model: str | None = None) -> None:
        self._connections = connections
        # Vectors of another model are not comparable; a re-embed pass can leave both for a while.
        self._model = embedding_model

    async def vector_search(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[Chunk]:
        where, params = _filter(labels)
        if self._model is not None:
            where = sql.SQL("{} AND embedding_model = %s").format(where)
            params = (*params, self._model)
        query = sql.SQL(
            "SELECT {} FROM chunks WHERE TRUE{} ORDER BY embedding <=> %s::vector LIMIT %s"
        ).format(_COLUMNS, where)
        async with (
            self._connections.connection() as conn,
            conn.transaction(),
        ):
            # With a label filter, keep scanning the HNSW graph until enough rows match.
            await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            cursor = conn.cursor(row_factory=dict_row)
            with SEARCH_SECONDS.labels("vector").time():
                await cursor.execute(query, (*params, vector_literal(embedding), limit))
                rows = await cursor.fetchall()
        return [Chunk(**row) for row in rows]

    async def text_search(self, query: str, labels: Sequence[UUID], limit: int) -> list[Chunk]:
        where, params = _filter(labels)
        # ||| matches any token; ### boosts tokens in order, so "2.5 mg twice daily" ranks above
        # "5 mg ... twice daily". A section title match ("Lactation") adds a smaller share.
        statement = sql.SQL(
            "SELECT {} FROM chunks "
            "WHERE (content ||| %s OR content ### %s::pdb.boost(2) "
            "OR section_title ||| %s::pdb.boost({})){} "
            "ORDER BY pdb.score(id) DESC LIMIT %s"
        ).format(_COLUMNS, sql.Literal(TITLE_BOOST), where)
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            with SEARCH_SECONDS.labels("bm25").time():
                await cursor.execute(statement, (query, query, query, *params, limit))
                rows = await cursor.fetchall()
        return [Chunk(**row) for row in rows]
