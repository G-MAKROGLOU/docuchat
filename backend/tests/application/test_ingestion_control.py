import asyncio
from datetime import UTC, datetime, timedelta

from app.application.ingestion_control import (
    IngestionControl,
    IngestionStatus,
    IngestWorker,
)
from app.domain.ingestion_state import IngestionPhase, IngestionState
from tests.support.tuning import HEARTBEAT, TICK

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


class FakeState:
    def __init__(self, phase: IngestionPhase = "idle", *, heartbeat: datetime | None = NOW) -> None:
        self.phase: IngestionPhase = phase
        self.force: bool | None = None
        self.next_run_at: datetime | None = LATER
        self.heartbeat_at = heartbeat
        self.reports: list[tuple[IngestionPhase, datetime | None]] = []

    async def load(self) -> IngestionState:
        return IngestionState(
            self.phase, self.force is not None, self.next_run_at, self.heartbeat_at
        )

    async def request(self, *, force: bool) -> None:
        self.force = force or bool(self.force)

    async def take(self) -> bool | None:
        force, self.force = self.force, None
        return force

    async def report(self, phase: IngestionPhase, next_run_at: datetime | None) -> None:
        self.phase, self.next_run_at, self.heartbeat_at = phase, next_run_at, NOW
        self.reports.append((phase, next_run_at))


def control(state: FakeState) -> IngestionControl:
    return IngestionControl(state, HEARTBEAT, clock=lambda: NOW)


def test_an_idle_worker_accepts_a_request_and_reports_it_as_running() -> None:
    state = FakeState()

    async def scenario() -> tuple[bool, IngestionStatus]:
        accepted = await control(state).request()
        return accepted, await control(state).status()

    accepted, status = asyncio.run(scenario())

    assert accepted
    assert status == IngestionStatus(running=True, phase="idle", next_run_at=LATER)


def test_a_request_is_refused_while_a_pass_runs() -> None:
    state = FakeState("ingesting")

    assert asyncio.run(control(state).request()) is False
    assert state.force is None


def test_a_second_request_is_refused_while_the_first_waits() -> None:
    state = FakeState()

    async def scenario() -> tuple[bool, bool]:
        return await control(state).request(), await control(state).request(force=True)

    assert asyncio.run(scenario()) == (True, False)
    assert state.force is False


def test_a_silent_worker_counts_as_idle_with_no_schedule() -> None:
    state = FakeState("ingesting", heartbeat=NOW - HEARTBEAT - timedelta(seconds=1))

    status = asyncio.run(control(state).status())

    assert status == IngestionStatus(running=False, phase="idle", next_run_at=None)


class FakeRunner:
    def __init__(self, *, running: bool = False) -> None:
        self.running = running
        self.phase: IngestionPhase = "checking" if running else "idle"
        self.next_run_at: datetime | None = LATER
        self.started: list[bool] = []

    def start(self, *, force: bool = False) -> bool:
        self.started.append(force)
        self.running, self.phase = True, "checking"
        return True


class Refresh:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        return False


def test_a_tick_refreshes_the_settings_takes_a_request_and_reports_the_new_phase() -> None:
    state, runner, refresh = FakeState(), FakeRunner(), Refresh()
    asyncio.run(state.request(force=True))

    asyncio.run(IngestWorker(runner, state, refresh, TICK).tick())

    assert refresh.calls == 1
    assert runner.started == [True]
    assert state.force is None
    assert state.reports == [("checking", LATER)]


def test_a_tick_leaves_a_request_waiting_while_a_pass_runs() -> None:
    state, runner = FakeState(), FakeRunner(running=True)
    asyncio.run(state.request(force=False))

    asyncio.run(IngestWorker(runner, state, Refresh(), TICK).tick())

    assert runner.started == []
    assert state.force is False
    assert state.reports == [("checking", LATER)]


def test_a_tick_without_a_request_only_reports() -> None:
    state, runner = FakeState(), FakeRunner()

    asyncio.run(IngestWorker(runner, state, Refresh(), TICK).tick())

    assert runner.started == []
    assert state.reports == [("idle", LATER)]
