import uuid

import pytest

from app.application.fusion import RRF_K, fuse, select
from app.domain.entities import Chunk

IDS = {name: uuid.uuid4() for name in "abcdefghijklmnop"}


def chunk(name: str, *, drug: str = "Lipitor", section: str = "1", tokens: int = 100) -> Chunk:
    return Chunk(
        id=IDS[name],
        document_id=uuid.uuid4(),
        drug_name=drug,
        section_number=section,
        section_title="T",
        page_start=1,
        page_end=1,
        content=name,
        anchor=name,
        token_count=tokens,
    )


def names(items: list) -> list[str]:  # type: ignore[type-arg]
    return [item.chunk.content for item in items]


def test_rrf_scores_and_order() -> None:
    a, b, c = chunk("a"), chunk("b"), chunk("c")

    fused = fuse(vector=[a, b], bm25=[b, c])

    assert names(fused) == ["b", "a", "c"]
    by_name = {f.chunk.content: f for f in fused}
    assert by_name["b"].score == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert (by_name["b"].vector_rank, by_name["b"].bm25_rank) == (2, 1)
    assert (by_name["a"].vector_rank, by_name["a"].bm25_rank) == (1, None)
    assert (by_name["c"].vector_rank, by_name["c"].bm25_rank) == (None, 2)


def test_ties_keep_a_stable_order() -> None:
    a, b = chunk("a"), chunk("b")

    assert names(fuse(vector=[a], bm25=[b])) == ["a", "b"]


def test_section_hint_boosts_close_scores() -> None:
    a, b = chunk("a", section="6.1"), chunk("b", section="2.1")

    fused = fuse(vector=[a, b], bm25=[], section_hints=("2",))

    assert names(fused) == ["b", "a"]
    assert fused[0].boosted


def test_section_hint_is_a_boost_not_a_filter() -> None:
    items = [chunk(n, section="6.1") for n in "abcdefgh"]
    hinted = chunk("i", section="2.1")

    fused = fuse(vector=[*items, hinted], bm25=items, section_hints=("2.1",))

    # Rank 1 in both lists beats a hinted chunk that is only rank 9 in one list.
    assert names(fused)[0] == "a"
    assert "i" in names(fused)


def test_select_takes_top_eight_within_the_token_budget() -> None:
    fused = fuse(vector=[chunk(n, tokens=400) for n in "abcdefghij"], bm25=[])

    selected = select(fused, drugs=())

    assert names(selected) == list("abcdefgh")
    assert sum(s.chunk.token_count for s in selected) <= 3500


def test_select_stops_at_the_token_budget() -> None:
    fused = fuse(vector=[chunk(n, tokens=1000) for n in "abcde"], bm25=[])

    assert names(select(fused, drugs=())) == ["a", "b", "c"]


def test_select_keeps_at_least_one_chunk_over_budget() -> None:
    fused = fuse(vector=[chunk("a", tokens=5000)], bm25=[])

    assert names(select(fused, drugs=())) == ["a"]


def test_two_drugs_get_at_least_three_chunks_each() -> None:
    eliquis = [chunk(n, drug="Eliquis") for n in "abcdefg"]
    xarelto = [chunk(n, drug="Xarelto") for n in "hijk"]

    selected = select(fuse(vector=[*eliquis, *xarelto], bm25=[]), drugs=("Eliquis", "Xarelto"))

    by_drug = [s.chunk.drug_name for s in selected]
    assert by_drug.count("Xarelto") >= 3
    assert by_drug.count("Eliquis") >= 3
    assert len(selected) == 8
    # The result stays in fused order.
    scores = [s.score for s in selected]
    assert scores == sorted(scores, reverse=True)


def test_a_drug_with_fewer_chunks_gives_what_it_has() -> None:
    eliquis = [chunk(n, drug="Eliquis") for n in "abcdefg"]
    xarelto = [chunk("h", drug="Xarelto")]

    selected = select(fuse(vector=[*eliquis, *xarelto], bm25=[]), drugs=("Eliquis", "Xarelto"))

    assert [s.chunk.drug_name for s in selected].count("Xarelto") == 1
    assert len(selected) == 8


def test_large_chunks_still_give_each_drug_a_chunk() -> None:
    eliquis = [chunk(n, drug="Eliquis", tokens=1200) for n in "abcd"]
    xarelto = [chunk(n, drug="Xarelto", tokens=1200) for n in "hij"]

    selected = select(fuse(vector=[*eliquis, *xarelto], bm25=[]), drugs=("Eliquis", "Xarelto"))

    assert names(selected) == ["a", "h"]
