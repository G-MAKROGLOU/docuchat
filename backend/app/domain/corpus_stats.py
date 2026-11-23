"""Totals over the ingested chunks, and their repository port. No framework imports."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CorpusStats:
    chunk_count: int
    token_count: int
    embedding_models: list[str]


class CorpusStatsRepository(Protocol):
    async def stats(self) -> CorpusStats: ...

    async def document_counts(self) -> dict[str, int]:
        """Documents by status; statuses without documents are left out."""
        ...
