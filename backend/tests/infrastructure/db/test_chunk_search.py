"""PostgresChunkSearch on the fixture corpus (real embeddings). Needs TEST_DATABASE_URL."""

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from app.domain.documents import DocumentStatus
from app.domain.entities import Chunk
from app.infrastructure.chunk_repository import PostgresChunkRepository, vector_literal
from app.infrastructure.chunk_search import _COLUMNS, PostgresChunkSearch
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.migrations import apply_migrations
from tests.support.db import DirectConnections
from tests.support.factories import label_of, make_document
from tests.support.tuning import SETTINGS

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]
FIXTURE: dict[str, Any] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "retrieval_fixture.json").read_text(encoding="utf-8")
)
DRUGS = ("Fixtorvan", "Fixaban")
LABELS = tuple(label_of(name) for name in DRUGS)


@pytest.fixture(scope="module")
def search() -> Iterator[PostgresChunkSearch]:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    documents = {name: label_of(name) for name in DRUGS}
    with psycopg.connect(conninfo) as conn:
        conn.execute("DELETE FROM documents WHERE brand_name = ANY(%s)", (list(DRUGS),))

    async def load() -> None:
        repo = PostgresDocumentRepository(DirectConnections(conninfo))
        for name, doc_id in documents.items():
            sha = uuid.uuid4().hex * 2
            await repo.add(
                make_document(
                    name,
                    name.lower(),
                    document_id=doc_id,
                    manufacturer="Fixture",
                    source_id=f"fixture-{name}",
                    sha=sha,
                    status=DocumentStatus.INGESTED,
                )
            )
        chunks = PostgresChunkRepository(DirectConnections(conninfo))
        for name, doc_id in documents.items():
            await chunks.replace_for_document(
                doc_id,
                [
                    Chunk(
                        id=uuid.uuid4(),
                        document_id=doc_id,
                        drug_name=c["drug_name"],
                        section_number=c["section_number"],
                        section_title=c["section_title"],
                        page_start=1,
                        page_end=1,
                        content=c["content"],
                        anchor=" ".join(c["content"].split()[:8]),
                        token_count=len(c["content"].split()),
                        embedding=tuple(c["embedding"]),
                        embedding_model=FIXTURE["model"],
                    )
                    for c in FIXTURE["chunks"]
                    if c["drug_name"] == name
                ],
            )

    asyncio.run(load())
    yield PostgresChunkSearch(
        DirectConnections(conninfo),
        None,
        title_boost=SETTINGS.search_title_boost,
        phrase_boost=SETTINGS.search_phrase_boost,
        hnsw_ef_search=SETTINGS.search_hnsw_ef_search,
    )
    with psycopg.connect(conninfo) as conn:
        conn.execute("DELETE FROM documents WHERE brand_name = ANY(%s)", (list(DRUGS),))


def query(name: str) -> dict[str, Any]:
    return FIXTURE["queries"][name]  # type: ignore[no-any-return]


def test_bm25_finds_the_exact_dose_string(search: PostgresChunkSearch) -> None:
    results = asyncio.run(search.text_search(query("exact_dose")["text"], LABELS, 20))

    assert "2.5 mg twice daily" in results[0].content


def test_vector_search_finds_the_paraphrased_question(search: PostgresChunkSearch) -> None:
    q = query("paraphrase")
    vector = asyncio.run(search.vector_search(q["embedding"], LABELS, 20))
    bm25 = asyncio.run(search.text_search(q["text"], LABELS, 20))

    assert vector[0].section_number == "5.1"  # myopathy and rhabdomyolysis
    # The words of the question are not in that chunk, so BM25 alone does not rank it first.
    assert not bm25 or bm25[0].section_number != "5.1"


def test_the_label_filter_applies_to_both_searches(search: PostgresChunkSearch) -> None:
    q = query("exact_dose")
    vector = asyncio.run(search.vector_search(q["embedding"], [label_of("Fixtorvan")], 20))
    bm25 = asyncio.run(search.text_search("dose mg daily", [label_of("Fixtorvan")], 20))

    assert vector
    assert bm25
    assert {c.drug_name for c in vector + bm25} == {"Fixtorvan"}


def test_a_query_without_tokens_gives_no_rows(search: PostgresChunkSearch) -> None:
    assert asyncio.run(search.text_search("?? --", LABELS, 20)) == []


def test_vector_search_reads_only_chunks_of_the_query_model(
    search: PostgresChunkSearch,
) -> None:
    q = query("paraphrase")
    connections = search._connections
    same = PostgresChunkSearch(
        connections,
        FIXTURE["model"],
        title_boost=SETTINGS.search_title_boost,
        phrase_boost=SETTINGS.search_phrase_boost,
        hnsw_ef_search=SETTINGS.search_hnsw_ef_search,
    )
    other = PostgresChunkSearch(
        connections,
        "other/model",
        title_boost=SETTINGS.search_title_boost,
        phrase_boost=SETTINGS.search_phrase_boost,
        hnsw_ef_search=SETTINGS.search_hnsw_ef_search,
    )

    assert asyncio.run(same.vector_search(q["embedding"], LABELS, 20))
    assert asyncio.run(other.vector_search(q["embedding"], LABELS, 20)) == []
    # BM25 has no vectors, so a half-done re-embed keeps the text list.
    assert asyncio.run(other.text_search("dose mg daily", LABELS, 20))


def test_the_vector_search_orders_by_the_indexed_expression(search: PostgresChunkSearch) -> None:
    # The HNSW index is on embedding::halfvec(1536); another ORDER BY would scan the whole table.
    statement, params = search._vector_query(vector_literal(query("paraphrase")["embedding"]))(
        _COLUMNS, [], 20
    )
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        conn.execute("SET enable_seqscan = off")
        plan = conn.execute(sql.SQL("EXPLAIN {}").format(statement), params).fetchall()

    assert "chunks_embedding_half_idx" in "\n".join(row[0] for row in plan)


def test_one_query_per_leg_gives_each_label_its_own_top_k(search: PostgresChunkSearch) -> None:
    q = query("exact_dose")
    vector = asyncio.run(search.vector_search_each(q["embedding"], LABELS, 3))
    bm25 = asyncio.run(search.text_search_each("dose mg daily", LABELS, 3))

    for each, single in (
        (vector, [asyncio.run(search.vector_search(q["embedding"], [lb], 3)) for lb in LABELS]),
        (bm25, [asyncio.run(search.text_search("dose mg daily", [lb], 3)) for lb in LABELS]),
    ):
        assert [[c.id for c in items] for items in each] == [
            [c.id for c in items] for items in single
        ]
        assert [{c.document_id for c in items} for items in each] == [{lb} for lb in LABELS]
