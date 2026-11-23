"""Reciprocal rank fusion of the vector and BM25 lists, and context selection. Plain code."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domain.entities import Chunk


@dataclass(frozen=True, slots=True)
class SearchLimits:
    rrf_k: int
    max_chunks: int
    token_budget: int
    min_per_drug: int  # comparison: chunks kept per label before the others
    leg_timeout_seconds: float


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
    limits: SearchLimits,
    *,
    vector: Sequence[Chunk],
    bm25: Sequence[Chunk],
    section_hints: Sequence[str] = (),
) -> list[FusedChunk]:
    chunks: dict[object, Chunk] = {}
    ranks: dict[object, dict[str, int]] = {}
    for source, items in (("vector", vector), ("bm25", bm25)):
        for rank, chunk in enumerate(items, start=1):
            chunks.setdefault(chunk.id, chunk)
            ranks.setdefault(chunk.id, {})[source] = rank

    base = {key: sum(1 / (limits.rrf_k + rank) for rank in r.values()) for key, r in ranks.items()}
    # The hinted sections act as a third ranked list: hinted chunks, in fused order, add
    # 1 / (k + rank) like a search hit at that rank. A strong search hit can still win.
    hinted = sorted(
        (
            key
            for key, chunk in chunks.items()
            if _in_hinted_section(chunk.section_number, section_hints)
        ),
        key=lambda key: -base[key],
    )
    section_rank = {key: rank for rank, key in enumerate(hinted, start=1)}

    fused = []
    for key, chunk in chunks.items():
        r = ranks[key]
        hint = section_rank.get(key)
        fused.append(
            FusedChunk(
                chunk=chunk,
                score=base[key] + (1 / (limits.rrf_k + hint) if hint else 0.0),
                vector_rank=r.get("vector"),
                bm25_rank=r.get("bm25"),
                boosted=hint is not None,
            )
        )
    # sorted() is stable, so equal scores keep first-seen order (vector before BM25).
    return sorted(fused, key=lambda f: -f.score)


def select(
    limits: SearchLimits, fused: Sequence[FusedChunk], *, labels: Sequence[UUID]
) -> list[FusedChunk]:
    """Top chunks within the count and token limits; with 2+ labels, a minimum per label."""
    chosen: list[FusedChunk] = []
    comparison = len(labels) >= 2  # noqa: PLR2004
    if comparison:
        # Round robin over the labels, so the token budget cannot use up one label's share first.
        per_drug = [
            [f for f in fused if f.chunk.document_id == d][: limits.min_per_drug] for d in labels
        ]
        for rank in range(limits.min_per_drug):
            chosen.extend(items[rank] for items in per_drug if rank < len(items))
    for item in fused:
        if item not in chosen:
            chosen.append(item)

    selected: list[FusedChunk] = []
    tokens = 0
    covered: set[UUID] = set()
    for item in chosen:
        if len(selected) == limits.max_chunks:
            break
        drug = item.chunk.document_id
        # Like the first chunk overall, the first chunk of each compared label may pass the budget.
        first_of_drug = comparison and drug in labels and drug not in covered
        if selected and not first_of_drug and tokens + item.chunk.token_count > limits.token_budget:
            continue  # a smaller chunk later can still fit
        selected.append(item)
        tokens += item.chunk.token_count
        covered.add(drug)
    order = {id(f): i for i, f in enumerate(fused)}
    return sorted(selected, key=lambda f: order[id(f)])
