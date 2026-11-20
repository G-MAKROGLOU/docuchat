import asyncio
import uuid
from collections.abc import Sequence

import pytest

from app.application.retrieval import (
    EmbeddingModelMismatchError,
    RetrievalService,
    SearchMode,
)
from app.domain.entities import Chunk


def chunk(name: str, drug: str = "Lipitor") -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        drug_name=drug,
        section_number="1",
        section_title="T",
        page_start=1,
        page_end=1,
        content=name,
        anchor=name,
        token_count=10,
    )


class FakeSearch:
    def __init__(self, models: set[str] | None = None) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.models = models if models is not None else {"m"}
        self.a, self.b = chunk("a"), chunk("b")

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]:
        self.calls.append(("vector", tuple(drugs)))
        return [self.a, self.b]

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]:
        self.calls.append(("bm25", tuple(drugs)))
        return [self.b]

    async def embedding_models(self) -> set[str]:
        return self.models


class FakeEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.0]


def test_hybrid_runs_both_searches_with_the_same_filter() -> None:
    search, embedder = FakeSearch(), FakeEmbedder()

    result = asyncio.run(
        RetrievalService(search, embedder, "m").retrieve(
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
        RetrievalService(search, FakeEmbedder(), "m").retrieve("q", mode=SearchMode.VECTOR)
    )

    assert [c[0] for c in search.calls] == ["vector"]
    assert all(f.bm25_rank is None for f in result.candidates)


def test_bm25_only_mode_does_not_embed() -> None:
    search, embedder = FakeSearch(), FakeEmbedder()

    asyncio.run(RetrievalService(search, embedder, "m").retrieve("q", mode=SearchMode.BM25))

    assert [c[0] for c in search.calls] == ["bm25"]
    assert embedder.queries == []


def test_an_index_from_another_embedding_model_is_rejected() -> None:
    service = RetrievalService(FakeSearch(models={"old/model"}), FakeEmbedder(), "new/model")

    with pytest.raises(EmbeddingModelMismatchError, match="old/model"):
        asyncio.run(service.retrieve("q"))
