from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_document_repository,
    get_label_catalog,
    get_label_queue_repository,
)
from app.main import app
from tests.support.fakes_ingestion import FakeCatalog, FakeDocumentRepository, FakeQueue


@pytest.fixture
def label_client() -> Iterator[TestClient]:
    """The label API over an empty fake queue and library."""
    queue = FakeQueue()
    app.dependency_overrides[get_label_queue_repository] = lambda: queue
    app.dependency_overrides[get_label_catalog] = FakeCatalog
    documents = FakeDocumentRepository()
    app.dependency_overrides[get_document_repository] = lambda: documents
    yield TestClient(app)
