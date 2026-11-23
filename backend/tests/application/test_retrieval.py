import asyncio
from collections.abc import Sequence

from app.application.retrieval import (
    RetrievalService,
    SearchMode,
)
from app.domain.entities import Chunk
from tests.support.factories import make_chunk
from tests.support.fakes_ingestion import QueryEmbedder


def chunk(name: str, drug: str = "Lipitor") -> Chunk:
    return make_chunk(name, drug=drug, section="1", title="T", page_start=1)


class FakeSearch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.a, self.b = chunk("a"), chunk("b")

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]:
        self.calls.append(("vector", tuple(drugs)))
        return [self.a, self.b]

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]:
        self.calls.append(("bm25", tuple(drugs)))
        return [self.b]


def test_hybrid_runs_both_searches_with_the_same_filter() -> None:
    search, embedder = FakeSearch(), QueryEmbedder()

    result = asyncio.run(
        RetrievalService(search, embedder, top_k=20).retrieve(
            "dose?", drugs=["Lipitor"], section_hints=["2"]
        )
    )

    assert sorted(search.calls) == [("bm25", ("Lipitor",)), ("vector", ("Lipitor",))]
    assert embedder.queries == ["dose?"]
    assert [f.chunk.content for f in result.candidates] == ["b", "a"]
    assert (result.drugs, result.section_hints, result.mode) == (
        ("Lipitor",),
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


class PerDrugSearch:
    """Each search returns chunks of the drugs in its filter, and records the filter."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]:
        self.calls.append(("vector", tuple(drugs)))
        return [chunk(f"v-{d}", d) for d in drugs]

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]:
        self.calls.append(("bm25", tuple(drugs)))
        return [chunk(f"b-{d}", d) for d in drugs]


def test_a_comparison_searches_each_drug_on_its_own_and_embeds_the_question_once() -> None:
    search, embedder = PerDrugSearch(), QueryEmbedder()

    result = asyncio.run(
        RetrievalService(search, embedder, top_k=20).retrieve("compare", drugs=("A", "B"))
    )

    assert sorted(search.calls) == [
        ("bm25", ("A",)),
        ("bm25", ("B",)),
        ("vector", ("A",)),
        ("vector", ("B",)),
    ]
    assert embedder.queries == ["compare"]
    # Both drugs are in the candidates, not only the one that ranks first.
    assert {f.chunk.drug_name for f in result.candidates} == {"A", "B"}


def test_one_drug_is_searched_once_with_its_filter() -> None:
    search = PerDrugSearch()

    asyncio.run(RetrievalService(search, QueryEmbedder(), top_k=20).retrieve("q", drugs=("A",)))

    assert sorted(search.calls) == [("bm25", ("A",)), ("vector", ("A",))]
