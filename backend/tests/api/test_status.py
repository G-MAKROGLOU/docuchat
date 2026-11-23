from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_corpus_stats_repository, get_ingestion_control
from app.main import app
from tests.support.fakes_ingestion import FakeCorpusStats, IdleControl


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_corpus_stats_repository] = FakeCorpusStats
    app.dependency_overrides[get_ingestion_control] = IdleControl
    yield TestClient(app)


def test_status_returns_the_corpus_totals(client: TestClient) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json() == {
        "chunk_count": 3864,
        "token_count": 1066576,
        "embedding_models": ["m1"],
        "ingestion_running": False,
        "ingestion_phase": "idle",
        "next_run_at": None,
        "document_counts": {"stored": 0, "ingesting": 0, "ingested": 48, "failed": 2},
    }
