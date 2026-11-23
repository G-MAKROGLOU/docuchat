"""Status codes of the error paths that the route tests do not cover."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.api.dependencies import get_chat_service, get_document_repository
from app.application.chat import MAX_QUESTION_CHARS, ChatService
from app.application.drug_detection import DrugDetection
from app.main import app
from tests.support.fakes_models import FakeModels
from tests.support.fakes_ports import FakeConversations, FakeDetector, FakeRetriever, FakeTracer
from tests.support.tuning import CHAT


@pytest.fixture
def client() -> Iterator[TestClient]:
    service = ChatService(
        FakeConversations(),
        FakeModels(),
        FakeDetector(DrugDetection()).source,
        FakeRetriever(),
        FakeTracer(),
        limits=CHAT,
    )
    app.dependency_overrides[get_chat_service] = lambda: service
    yield TestClient(app, raise_server_exceptions=False)


def test_a_new_conversation_is_created_with_201(client: TestClient) -> None:
    response = client.post("/api/v1/conversations")

    assert response.status_code == 201
    assert uuid.UUID(response.json()["id"])


def test_a_blank_or_too_long_question_and_a_bad_id_are_rejected(client: TestClient) -> None:
    conversation_id = client.post("/api/v1/conversations").json()["id"]
    too_long = {"text": "a" * (MAX_QUESTION_CHARS + 1)}
    blank = {"text": " \n\t "}

    assert (
        client.post(f"/api/v1/conversations/{conversation_id}/messages", json=too_long).status_code
        == 422
    )
    assert (
        client.post(f"/api/v1/conversations/{conversation_id}/messages", json=blank).status_code
        == 422
    )
    assert client.get("/api/v1/conversations/not-a-uuid").status_code == 422
    assert (
        client.post("/api/v1/conversations/not-a-uuid/messages", json={"text": "hi"}).status_code
        == 422
    )


def _server_errors() -> float:
    return sum(
        sample.value
        for metric in REGISTRY.collect()
        if metric.name == "docuchat_http_requests"
        for sample in metric.samples
        if sample.name.endswith("_total") and sample.labels.get("status") == "500"
    )


def test_an_unhandled_error_returns_500_and_is_counted(client: TestClient) -> None:
    def broken() -> object:
        raise RuntimeError("database down")

    app.dependency_overrides[get_document_repository] = broken
    before = _server_errors()

    response = client.get("/api/v1/documents")

    assert response.status_code == 500
    assert "database down" not in response.text
    assert _server_errors() == before + 1
