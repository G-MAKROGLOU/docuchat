"""Ingestion across processes: the API asks for passes and reads the state, the one ingest
worker runs the passes. They meet in the shared IngestionStateRepository."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.domain.ingestion_state import IngestionPhase, IngestionStateRepository

logger = logging.getLogger(__name__)

# The worker reports every TICK; after HEARTBEAT_LIMIT without a report it counts as gone.
TICK = timedelta(seconds=1)
HEARTBEAT_LIMIT = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class IngestionStatus:
    running: bool
    phase: IngestionPhase
    next_run_at: datetime | None


class IngestionControl:
    """The API side: no pass runs in this process."""

    def __init__(
        self,
        state: IngestionStateRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._state = state
        self._clock = clock

    async def status(self) -> IngestionStatus:
        state = await self._state.load()
        alive = state.heartbeat_at is not None and (
            self._clock() - state.heartbeat_at <= HEARTBEAT_LIMIT
        )
        phase: IngestionPhase = state.phase if alive else "idle"
        return IngestionStatus(
            running=state.requested or phase != "idle",
            phase=phase,
            next_run_at=state.next_run_at if alive else None,
        )

    async def heartbeat_age(self) -> float | None:
        """Seconds since the worker last reported; None when it never did."""
        state = await self._state.load()
        if state.heartbeat_at is None:
            return None
        return (self._clock() - state.heartbeat_at).total_seconds()

    async def request(self, *, force: bool = False) -> bool:
        """Ask for a pass. False when one runs or waits already."""
        if (await self.status()).running:
            return False
        await self._state.request(force=force)
        return True


class PassRunner(Protocol):
    @property
    def running(self) -> bool: ...

    @property
    def phase(self) -> IngestionPhase: ...

    @property
    def next_run_at(self) -> datetime | None: ...

    def start(self, *, force: bool = False) -> bool: ...


class IngestWorker:
    """The worker side: takes requests, runs them one at a time, reports its phase."""

    def __init__(
        self,
        runner: PassRunner,
        state: IngestionStateRepository,
        refresh_settings: Callable[[], Awaitable[bool]],
    ) -> None:
        self._runner = runner
        self._state = state
        self._refresh_settings = refresh_settings

    async def tick(self) -> None:
        # Settings first: a request that a settings change made must use the new settings.
        await self._refresh_settings()
        if not self._runner.running:
            force = await self._state.take()
            if force is not None:
                self._runner.start(force=force)
        await self._state.report(self._runner.phase, self._runner.next_run_at)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("ingest worker tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), TICK.total_seconds())
