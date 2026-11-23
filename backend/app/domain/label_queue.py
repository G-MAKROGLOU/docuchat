"""The label queue: labels that the user wants in the corpus, and the catalogue that knows
them. No framework imports."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class QueueStatus(StrEnum):
    QUEUED = "queued"
    ADDED = "added"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CatalogLabel:
    set_id: str
    title: str
    version: int
    published: str


@dataclass(frozen=True, slots=True)
class LabelMetadata:
    brand_name: str
    generic_name: str
    manufacturer: str
    dosage_form: str = ""  # SPL form, for example "TABLET, FILM COATED"


@dataclass(frozen=True, slots=True)
class QueueEntry:
    set_id: str
    title: str
    status: QueueStatus
    failure_reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QueueListing:
    """One page of the queue, and the number of entries in each state."""

    entries: list[QueueEntry]
    queued_total: int
    added_total: int
    failed_total: int

    @property
    def total(self) -> int:
        return self.queued_total + self.added_total + self.failed_total


class LabelCatalog(Protocol):
    """The public catalogue of labels."""

    def lookup(self, set_id: str) -> CatalogLabel | None:
        """The label with this set ID, or None when the catalogue does not know it."""
        ...

    def search(self, drug_name: str, limit: int) -> list[CatalogLabel]: ...


class LabelMetadataReader(Protocol):
    def metadata(self, data: bytes) -> LabelMetadata:
        """The names of the product and its manufacturer, read from a structured label."""
        ...


class LabelQueueRepository(Protocol):
    async def add(self, set_id: str, title: str) -> bool:
        """Queue a label. A failed entry is queued again. False when the entry exists
        in another state."""
        ...

    async def list_page(self, page: int, page_size: int) -> QueueListing:
        """Entries that need attention (queued, failed) first, then added ones; newest first."""
        ...

    async def next_queued(self, limit: int) -> list[QueueEntry]:
        """The oldest queued entries first."""
        ...

    async def mark(self, set_id: str, status: QueueStatus, failure_reason: str | None) -> None: ...

    async def known(self, set_ids: Sequence[str]) -> set[str]:
        """The set IDs among these that are in the queue, in any state."""
        ...

    async def remove(self, set_id: str) -> bool:
        """Remove a queued or failed entry. False when none was removed."""
        ...
