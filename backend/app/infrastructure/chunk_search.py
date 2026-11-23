"""ChunkSearch adapter: pgvector HNSW (cosine) and ParadeDB BM25, with the same label filter."""

from collections.abc import Callable, Sequence
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
# HNSW candidate list. At 1M chunks, recall@20 was 0.72 with the default 40 and 0.80 with 120,
# about 2 ms slower (docs/agent-log.md, 2026-11-23).
HNSW_EF_SEARCH = 120

Query = tuple[sql.Composed, tuple[Any, ...]]
# Builds one search: (select list, labels, limit) -> statement and parameters.
Build = Callable[[sql.Composable, Sequence[UUID], int], Query]


def ef_search(limit: int) -> int:
    return max(HNSW_EF_SEARCH, 2 * limit)


def _filter(labels: Sequence[UUID]) -> tuple[sql.Composable, tuple[Any, ...]]:
    if not labels:
        return sql.SQL(""), ()
    return sql.SQL(" AND document_id = ANY(%s)"), (list(labels),)


def _per_label(build: Build, labels: Sequence[UUID], limit: int) -> Query:
    """One UNION ALL branch per label with its own ORDER BY and LIMIT, so each branch keeps the
    plan of a one-label search (a window function loses the pg_search TopK scan)."""
    parts: list[sql.Composable] = []
    params: list[Any] = []
    for position, label in enumerate(labels):
        select = sql.SQL("{} AS part, {}").format(sql.Literal(position), _COLUMNS)
        statement, values = build(select, [label], limit)
        parts.append(sql.SQL("({})").format(statement))
        params.extend(values)
    return sql.SQL(" UNION ALL ").join(parts), tuple(params)


def _split(rows: Sequence[dict[str, Any]], count: int) -> list[list[Chunk]]:
    lists: list[list[Chunk]] = [[] for _ in range(count)]
    for row in rows:
        lists[row.pop("part")].append(Chunk(**row))
    return lists


class PostgresChunkSearch:
    def __init__(self, connections: Connections, embedding_model: str | None = None) -> None:
        self._connections = connections
        # Vectors of another model are not comparable; a re-embed pass can leave both for a while.
        self._model = embedding_model

    def _vector_query(self, vector: str) -> Build:
        def build(select: sql.Composable, labels: Sequence[UUID], limit: int) -> Query:
            where, params = _filter(labels)
            if self._model is not None:
                where = sql.SQL("{} AND embedding_model = %s").format(where)
                params = (*params, self._model)
            # The same expression as the HNSW index (0014): half precision, half the index size.
            statement = sql.SQL(
                "SELECT {} FROM chunks WHERE TRUE{} "
                "ORDER BY embedding::halfvec(1536) <=> %s::halfvec(1536) LIMIT %s"
            ).format(select, where)
            return statement, (*params, vector, limit)

        return build

    @staticmethod
    def _text_query(query: str) -> Build:
        def build(select: sql.Composable, labels: Sequence[UUID], limit: int) -> Query:
            where, params = _filter(labels)
            # ||| matches any token; ### boosts tokens in order, so "2.5 mg twice daily" ranks
            # above "5 mg ... twice daily". A section title match ("Lactation") adds less.
            statement = sql.SQL(
                "SELECT {} FROM chunks "
                "WHERE (content ||| %s OR content ### %s::pdb.boost(2) "
                "OR section_title ||| %s::pdb.boost({})){} "
                "ORDER BY pdb.score(id) DESC LIMIT %s"
            ).format(select, sql.Literal(TITLE_BOOST), where)
            return statement, (query, query, query, *params, limit)

        return build

    async def _vector_rows(self, statement: Query, limit: int) -> list[dict[str, Any]]:
        async with (
            self._connections.connection() as conn,
            conn.transaction(),
        ):
            # With a label filter, keep scanning the HNSW graph until enough rows match.
            await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            await conn.execute(
                sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(ef_search(limit)))
            )
            cursor = conn.cursor(row_factory=dict_row)
            with SEARCH_SECONDS.labels("vector").time():
                await cursor.execute(*statement)
                return await cursor.fetchall()

    async def _text_rows(self, statement: Query) -> list[dict[str, Any]]:
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            with SEARCH_SECONDS.labels("bm25").time():
                await cursor.execute(*statement)
                return await cursor.fetchall()

    async def vector_search(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[Chunk]:
        build = self._vector_query(vector_literal(embedding))
        return [
            Chunk(**row) for row in await self._vector_rows(build(_COLUMNS, labels, limit), limit)
        ]

    async def text_search(self, query: str, labels: Sequence[UUID], limit: int) -> list[Chunk]:
        build = self._text_query(query)
        return [Chunk(**row) for row in await self._text_rows(build(_COLUMNS, labels, limit))]

    async def vector_search_each(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        if not labels:
            return []
        build = self._vector_query(vector_literal(embedding))
        return _split(await self._vector_rows(_per_label(build, labels, limit), limit), len(labels))

    async def text_search_each(
        self, query: str, labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        if not labels:
            return []
        build = self._text_query(query)
        return _split(await self._text_rows(_per_label(build, labels, limit)), len(labels))
