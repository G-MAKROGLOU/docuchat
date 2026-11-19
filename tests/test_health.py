from fastapi.testclient import TestClient

from app.api.dependencies import get_database_probe
from app.infrastructure.database import DatabaseStatus
from app.main import app


class FakeProbe:
    async def check(self) -> DatabaseStatus:
        return DatabaseStatus(connected=True, extensions=["pg_search", "plpgsql", "vector"])


def test_health_reports_database_and_extensions() -> None:
    app.dependency_overrides[get_database_probe] = FakeProbe
    try:
        response = TestClient(app).get("/health", headers={"x-request-id": "abc"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "abc"
    assert response.json() == {
        "status": "ok",
        "database": {"connected": True, "extensions": ["pg_search", "plpgsql", "vector"]},
    }
