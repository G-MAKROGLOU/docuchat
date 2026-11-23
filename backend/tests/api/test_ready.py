import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_readiness_checks
from app.application.ingestion_control import IngestionControl
from app.application.readiness import ReadinessCheck, run_checks
from app.domain.ingestion_state import IngestionState
from app.main import app
from tests.support.tuning import HEARTBEAT


async def ok() -> tuple[bool, str | None]:
    return True, None


async def stale() -> tuple[bool, str | None]:
    return False, "last heartbeat 90 s ago"


async def broken() -> tuple[bool, str | None]:
    raise ConnectionError("connect to http://storage:8333 with key secret-123 failed")


async def hangs() -> tuple[bool, str | None]:
    await asyncio.sleep(5)
    return True, None


def test_a_failing_check_reports_only_the_error_type() -> None:
    ready, results = asyncio.run(run_checks([ReadinessCheck("storage", True, broken)], 1.0))

    assert not ready
    assert (results[0].ok, results[0].detail) == (False, "failed (ConnectionError)")


def test_a_check_that_hangs_is_cut_off_at_the_timeout() -> None:
    ready, results = asyncio.run(run_checks([ReadinessCheck("database", True, hangs)], 0.05))

    assert not ready
    assert results[0].detail == "timed out after 0.05 s"
    assert results[0].duration_ms < 1000


def test_a_failing_optional_check_keeps_the_service_ready() -> None:
    checks = [ReadinessCheck("database", True, ok), ReadinessCheck("worker", False, stale)]

    ready, results = asyncio.run(run_checks(checks, 1.0))

    assert ready
    assert [(r.name, r.ok, r.required) for r in results] == [
        ("database", True, True),
        ("worker", False, False),
    ]


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)


def test_ready_answers_200_when_the_required_checks_pass(client: TestClient) -> None:
    app.dependency_overrides[get_readiness_checks] = lambda: [
        ReadinessCheck("database", True, ok),
        ReadinessCheck("worker", False, stale),
    ]

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"][1] == {
        "name": "worker",
        "ok": False,
        "required": False,
        "detail": "last heartbeat 90 s ago",
        "duration_ms": body["checks"][1]["duration_ms"],
    }


def test_ready_answers_503_when_a_required_check_fails(client: TestClient) -> None:
    app.dependency_overrides[get_readiness_checks] = lambda: [
        ReadinessCheck("storage", True, broken)
    ]

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "secret" not in response.text


class State:
    def __init__(self, heartbeat: datetime | None) -> None:
        self.heartbeat = heartbeat

    async def load(self) -> IngestionState:
        return IngestionState(
            "idle", requested=False, next_run_at=None, heartbeat_at=self.heartbeat
        )


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(("heartbeat", "age"), [(None, None), (NOW - timedelta(seconds=42), 42.0)])
def test_the_control_reports_the_heartbeat_age(
    heartbeat: datetime | None, age: float | None
) -> None:
    control = IngestionControl(State(heartbeat), HEARTBEAT, clock=lambda: NOW)  # type: ignore[arg-type]

    assert asyncio.run(control.heartbeat_age()) == age
