"""The shared state of the ingest worker, and its repository port. No framework imports."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

IngestionPhase = Literal["idle", "checking", "downloading", "ingesting"]


@dataclass(frozen=True, slots=True)
class IngestionState:
    phase: IngestionPhase
    # A pass that an API process asked for and the worker has not taken yet.
    requested: bool
    next_run_at: datetime | None
    # The last report of the worker. None when no worker has reported.
    heartbeat_at: datetime | None


class IngestionStateRepository(Protocol):
    async def load(self) -> IngestionState: ...

    async def request(self, *, force: bool) -> None:
        """Ask the worker for a pass. A waiting request keeps force if either asked for it."""

    async def take(self) -> bool | None:
        """Clear the waiting request and return its force flag. None when nothing waits."""

    async def report(self, phase: IngestionPhase, next_run_at: datetime | None) -> None:
        """The worker's phase and next scheduled pass; also the heartbeat."""
