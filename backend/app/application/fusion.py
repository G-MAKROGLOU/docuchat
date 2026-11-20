"""Reciprocal rank fusion of the vector and BM25 lists, and context selection. Plain code."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.entities import Chunk

RRF_K = 60
# Added to the fused score of a chunk in a hinted section: about the gap between two
# neighbouring ranks near the top, so it reorders close results but not distant ones.
SECTION_BOOST = 0.0003
MAX_CHUNKS = 8
TOKEN_BUDGET = 3500
MIN_PER_DRUG = 3


@dataclass(frozen=True, slots=True)
class FusedChunk:
    chunk: Chunk
    score: float
    vector_rank: int | None
    bm25_rank: int | None
    boosted: bool = False


def _in_hinted_section(section: str, hints: Sequence[str]) -> bool:
    return any(section == h or section.startswith(f"{h}.") for h in hints)


def fuse(
    *, vector: Sequence[Chunk], bm25: Sequence[Chunk], section_hints: Sequence[str] = ()
) -> list[FusedChunk]:
    chunks: dict[object, Chunk] = {}
    ranks: dict[object, dict[str, int]] = {}
    for source, items in (("vector", vector), ("bm25", bm25)):
        for rank, chunk in enumerate(items, start=1):
            chunks.setdefault(chunk.id, chunk)
            ranks.setdefault(chunk.id, {})[source] = rank

    fused = []
    for key, chunk in chunks.items():
        r = ranks[key]
        score = sum(1 / (RRF_K + rank) for rank in r.values())
        boosted = _in_hinted_section(chunk.section_number, section_hints)
        fused.append(
            FusedChunk(
                chunk=chunk,
                score=score + (SECTION_BOOST if boosted else 0.0),
                vector_rank=r.get("vector"),
                bm25_rank=r.get("bm25"),
                boosted=boosted,
            )
        )
    # sorted() is stable, so equal scores keep first-seen order (vector before BM25).
    return sorted(fused, key=lambda f: -f.score)


def select(fused: Sequence[FusedChunk], *, drugs: Sequence[str]) -> list[FusedChunk]:
    """Top chunks within the count and token limits; with 2+ drugs, a minimum per drug."""
    chosen: list[FusedChunk] = []
    if len(drugs) >= 2:  # noqa: PLR2004  # a comparison question
        for drug in drugs:
            chosen.extend([f for f in fused if f.chunk.drug_name == drug][:MIN_PER_DRUG])
    for item in fused:
        if item not in chosen:
            chosen.append(item)

    selected: list[FusedChunk] = []
    tokens = 0
    for item in chosen:
        if len(selected) == MAX_CHUNKS:
            break
        if selected and tokens + item.chunk.token_count > TOKEN_BUDGET:
            break
        selected.append(item)
        tokens += item.chunk.token_count
    order = {id(f): i for i, f in enumerate(fused)}
    return sorted(selected, key=lambda f: order[id(f)])
