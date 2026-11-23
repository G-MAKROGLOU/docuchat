import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_document_repository, get_document_store
from app.domain.documents import Document
from app.infrastructure.storage import FileSystemDocumentStore
from app.main import app
from tests.support.factories import make_document
from tests.support.fakes_ingestion import FakeDocumentRepository

PDF = b"%PDF-1.4\n" + bytes(range(256)) * 400


@pytest.fixture
def document(tmp_path: Path) -> Iterator[Document]:
    store = FileSystemDocumentStore(tmp_path)
    doc = make_document(size_bytes=len(PDF))
    store.put(doc.storage_key, PDF, "application/pdf")
    app.dependency_overrides[get_document_repository] = lambda: FakeDocumentRepository(doc)
    app.dependency_overrides[get_document_store] = lambda: store
    yield doc


def url(doc: Document) -> str:
    return f"/api/v1/documents/{doc.id}/file"


def test_full_file_streams_with_range_support(document: Document) -> None:
    response = TestClient(app).get(url(document))

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(PDF))


def test_range_request_returns_partial_content(document: Document) -> None:
    response = TestClient(app).get(url(document), headers={"Range": "bytes=100-199"})

    assert response.status_code == 206
    assert response.content == PDF[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(PDF)}"
    assert response.headers["content-length"] == "100"


def test_open_ended_range(document: Document) -> None:
    response = TestClient(app).get(url(document), headers={"Range": "bytes=-10"})

    assert response.status_code == 206
    assert response.content == PDF[-10:]


def test_unsatisfiable_range(document: Document) -> None:
    response = TestClient(app).get(url(document), headers={"Range": f"bytes={len(PDF)}-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(PDF)}"


def test_unknown_document_is_404(document: Document) -> None:
    response = TestClient(app).get(f"/api/v1/documents/{uuid.uuid4()}/file")

    assert response.status_code == 404


def test_missing_stored_object_is_404(document: Document, tmp_path: Path) -> None:
    FileSystemDocumentStore(tmp_path).delete(document.storage_key)
    client = TestClient(app)

    assert client.get(url(document)).status_code == 404
    assert client.get(url(document), headers={"Range": "bytes=0-9"}).status_code == 404


class CountingStore(FileSystemDocumentStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.exists_calls = 0

    def exists(self, key: str) -> bool:
        self.exists_calls += 1
        return super().exists(key)


def test_file_requests_read_the_object_without_an_existence_check(
    document: Document, tmp_path: Path
) -> None:
    store = CountingStore(tmp_path)
    app.dependency_overrides[get_document_store] = lambda: store
    client = TestClient(app)

    assert client.get(url(document)).content == PDF
    assert client.get(url(document), headers={"Range": "bytes=0-9"}).status_code == 206
    assert store.exists_calls == 0
