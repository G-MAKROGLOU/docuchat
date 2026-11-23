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

from app.domain.documents import DocumentStatus
from app.domain.entities import Chunk
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.chunk_search import PostgresChunkSearch
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.migrations import apply_migrations
from tests.support.db import DirectConnections
from tests.support.factories import label_of, make_document

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
    yield PostgresChunkSearch(DirectConnections(conninfo))
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
    same = PostgresChunkSearch(connections, FIXTURE["model"])
    other = PostgresChunkSearch(connections, "other/model")

    assert asyncio.run(same.vector_search(q["embedding"], LABELS, 20))
    assert asyncio.run(other.vector_search(q["embedding"], LABELS, 20)) == []
    # BM25 has no vectors, so a half-done re-embed keeps the text list.
    assert asyncio.run(other.text_search("dose mg daily", LABELS, 20))
