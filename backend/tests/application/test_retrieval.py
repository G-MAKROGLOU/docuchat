import asyncio
from collections.abc import Sequence
from uuid import UUID

import pytest

from app.application import retrieval
from app.application.retrieval import (
    RetrievalService,
    SearchMode,
)
from app.domain.entities import Chunk
from tests.support.factories import label_of, make_chunk
from tests.support.fakes_ingestion import QueryEmbedder


def chunk(name: str, drug: str = "Lipitor") -> Chunk:
    return make_chunk(name, drug=drug, section="1", title="T", page_start=1)


class FakeSearch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[UUID, ...]]] = []
        self.a, self.b = chunk("a"), chunk("b")

    async def vector_search(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[Chunk]:
        self.calls.append(("vector", tuple(labels)))
        return [self.a, self.b]

    async def text_search(self, query: str, labels: Sequence[UUID], limit: int) -> list[Chunk]:
        self.calls.append(("bm25", tuple(labels)))
        return [self.b]

    async def vector_search_each(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        return [await self.vector_search(embedding, [label], limit) for label in labels]

    async def text_search_each(
        self, query: str, labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        return [await self.text_search(query, [label], limit) for label in labels]


def test_hybrid_runs_both_searches_with_the_same_filter() -> None:
    search, embedder = FakeSearch(), QueryEmbedder()

    result = asyncio.run(
        RetrievalService(search, embedder, top_k=20).retrieve(
            "dose?", labels=[label_of("Lipitor")], section_hints=["2"]
        )
    )

    assert sorted(search.calls) == [
        ("bm25", (label_of("Lipitor"),)),
        ("vector", (label_of("Lipitor"),)),
    ]
    assert embedder.queries == ["dose?"]
    assert [f.chunk.content for f in result.candidates] == ["b", "a"]
    assert (result.labels, result.section_hints, result.mode) == (
        (label_of("Lipitor"),),
        ("2",),
        SearchMode.HYBRID,
    )
    top = result.selected[0]
    assert (top.vector_rank, top.bm25_rank) == (2, 1)


def test_vector_only_mode_skips_bm25() -> None:
    search = FakeSearch()

    result = asyncio.run(
        RetrievalService(search, QueryEmbedder(), top_k=20).retrieve("q", mode=SearchMode.VECTOR)
    )

    assert [c[0] for c in search.calls] == ["vector"]
    assert all(f.bm25_rank is None for f in result.candidates)


def test_bm25_only_mode_does_not_embed() -> None:
    search, embedder = FakeSearch(), QueryEmbedder()

    asyncio.run(RetrievalService(search, embedder, top_k=20).retrieve("q", mode=SearchMode.BM25))

    assert [c[0] for c in search.calls] == ["bm25"]
    assert embedder.queries == []


DRUG_OF = {label_of(name): name for name in "AB"}


class PerDrugSearch:
    """Each search returns chunks of the labels in its filter, and records the drug names."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def vector_search(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[Chunk]:
        self.calls.append(("vector", tuple(DRUG_OF[label] for label in labels)))
        return [chunk(f"v-{DRUG_OF[label]}", DRUG_OF[label]) for label in labels]

    async def text_search(self, query: str, labels: Sequence[UUID], limit: int) -> list[Chunk]:
        self.calls.append(("bm25", tuple(DRUG_OF[label] for label in labels)))
        return [chunk(f"b-{DRUG_OF[label]}", DRUG_OF[label]) for label in labels]

    async def vector_search_each(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        self.calls.append(("vector_each", tuple(DRUG_OF[label] for label in labels)))
        return [
            [chunk(f"v-{DRUG_OF[label]}-{i}", DRUG_OF[label]) for i in (1, 2)] for label in labels
        ]

    async def text_search_each(
        self, query: str, labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        self.calls.append(("bm25_each", tuple(DRUG_OF[label] for label in labels)))
        return [[chunk(f"b-{DRUG_OF[label]}", DRUG_OF[label])] for label in labels]


def test_a_comparison_runs_one_query_per_leg_and_embeds_the_question_once() -> None:
    search, embedder = PerDrugSearch(), QueryEmbedder()

    result = asyncio.run(
        RetrievalService(search, embedder, top_k=20).retrieve(
            "compare", labels=(label_of("A"), label_of("B"))
        )
    )

    assert sorted(search.calls) == [("bm25_each", ("A", "B")), ("vector_each", ("A", "B"))]
    assert embedder.queries == ["compare"]
    # Both drugs are in the candidates, not only the one that ranks first.
    assert {f.chunk.drug_name for f in result.candidates} == {"A", "B"}


def test_a_comparison_merges_the_label_lists_in_turn() -> None:
    result = asyncio.run(
        RetrievalService(PerDrugSearch(), QueryEmbedder(), top_k=20).retrieve(
            "compare", labels=(label_of("A"), label_of("B")), mode=SearchMode.VECTOR
        )
    )

    assert [f.chunk.content for f in result.candidates] == ["v-A-1", "v-B-1", "v-A-2", "v-B-2"]


def test_one_drug_is_searched_once_with_its_filter() -> None:
    search = PerDrugSearch()

    asyncio.run(
        RetrievalService(search, QueryEmbedder(), top_k=20).retrieve("q", labels=(label_of("A"),))
    )

    assert sorted(search.calls) == [("bm25", ("A",)), ("vector", ("A",))]


class FlakySearch(FakeSearch):
    """The vector leg fails or hangs; the BM25 leg answers."""

    def __init__(self, vector_error: Exception | None = None, vector_delay: float = 0.0) -> None:
        super().__init__()
        self.vector_error = vector_error
        self.vector_delay = vector_delay

    async def vector_search(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[Chunk]:
        await asyncio.sleep(self.vector_delay)
        if self.vector_error:
            raise self.vector_error
        return await super().vector_search(embedding, labels, limit)


def test_a_failed_search_leg_leaves_the_other_leg() -> None:
    search = FlakySearch(vector_error=TimeoutError("statement timeout"))

    result = asyncio.run(RetrievalService(search, QueryEmbedder(), top_k=20).retrieve("q"))

    assert [f.chunk.content for f in result.candidates] == ["b"]
    assert result.degraded == ("vector",)


def test_a_slow_search_leg_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval, "LEG_TIMEOUT_SECONDS", 0.05)
    search = FlakySearch(vector_delay=1.0)

    result = asyncio.run(RetrievalService(search, QueryEmbedder(), top_k=20).retrieve("q"))

    assert [f.chunk.content for f in result.candidates] == ["b"]
    assert result.degraded == ("vector",)


def test_a_failed_embedding_searches_with_bm25_only() -> None:
    class BrokenEmbedder(QueryEmbedder):
        async def embed_query(self, text: str) -> list[float]:
            raise ConnectionError("embedding API down")

    search = FakeSearch()

    result = asyncio.run(RetrievalService(search, BrokenEmbedder(), top_k=20).retrieve("q"))

    assert [c[0] for c in search.calls] == ["bm25"]
    assert result.degraded == ("embedding",)


def test_the_turn_fails_when_both_legs_fail() -> None:
    class DeadSearch(FlakySearch):
        async def text_search(self, query: str, labels: Sequence[UUID], limit: int) -> list[Chunk]:
            raise ConnectionError("database down")

    search = DeadSearch(vector_error=ConnectionError("database down"))

    with pytest.raises(ConnectionError):
        asyncio.run(RetrievalService(search, QueryEmbedder(), top_k=20).retrieve("q"))
