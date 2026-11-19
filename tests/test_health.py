from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_database_probe
from app.infrastructure.database import DatabaseStatus
from app.main import app

EXTENSIONS = ["pg_search", "plpgsql", "vector"]


class FakeProbe:
    def __init__(self, status: DatabaseStatus) -> None:
        self._status = status

    async def check(self) -> DatabaseStatus:
        return self._status


def client_with(status: DatabaseStatus) -> TestClient:
    app.dependency_overrides[get_database_probe] = lambda: FakeProbe(status)
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_health_reports_database_and_extensions() -> None:
    response = client_with(DatabaseStatus(connected=True, extensions=EXTENSIONS)).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": {"connected": True, "extensions": EXTENSIONS},
    }


def test_health_is_degraded_when_database_is_down() -> None:
    response = client_with(DatabaseStatus(connected=False, extensions=[])).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": {"connected": False, "extensions": []},
    }


def test_valid_request_id_is_echoed() -> None:
    client = client_with(DatabaseStatus(connected=True, extensions=[]))
    response = client.get("/health", headers={"x-request-id": "abc-123"})

    assert response.headers.get_list("x-request-id") == ["abc-123"]


def test_invalid_request_id_is_replaced() -> None:
    client = client_with(DatabaseStatus(connected=True, extensions=[]))
    response = client.get("/health", headers={"x-request-id": "bad id; forged=1"})

    request_id = response.headers["x-request-id"]
    assert request_id != "bad id; forged=1"
    assert len(request_id) == 32
