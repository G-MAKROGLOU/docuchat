import uuid
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_cache,
    get_document_repository,
    get_document_store,
    get_page_renderer,
)
from app.domain.documents import Document, DocumentStatus
from app.infrastructure.pdf_thumbnail import PyMuPdfPageRenderer
from app.infrastructure.storage import FileSystemDocumentStore
from app.main import app
from tests.support.factories import make_document, make_pdf
from tests.support.fakes_ingestion import FakeDocumentRepository
from tests.support.fakes_ports import FakeCache

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def library_document(brand: str, generic: str, sha: str) -> Document:
    return make_document(
        brand,
        generic,
        source_id=f"set-{sha[:4]}",
        sha=sha,
        size_bytes=100,
        status=DocumentStatus.INGESTED,
        page_count=3,
    )


class CountingRenderer:
    def __init__(self) -> None:
        self.widths: list[int] = []

    def render_first_page(self, pdf: bytes, width: int) -> bytes:
        self.widths.append(width)
        return PNG_SIGNATURE + b"fake"


DOCS = [
    library_document("Zeta", "zetamab", "1" * 64),
    library_document("", "alphacillin", "2" * 64),
    library_document("Beta", "betanol", "3" * 64),
]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    store = FileSystemDocumentStore(tmp_path)
    for doc in DOCS:
        store.put(doc.storage_key, make_pdf(pages=2, size=(600, 800)), "application/pdf")
    app.dependency_overrides[get_document_repository] = lambda: FakeDocumentRepository(*DOCS)
    app.dependency_overrides[get_document_store] = lambda: store
    cache = FakeCache()
    app.dependency_overrides[get_cache] = lambda: cache
    yield TestClient(app)


def test_list_orders_by_brand_or_generic_name(client: TestClient) -> None:
    body = client.get("/api/v1/documents").json()

    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert [i["generic_name"] for i in body["items"]] == ["alphacillin", "betanol", "zetamab"]
    assert body["items"][0] == {
        "id": str(DOCS[1].id),
        "brand_name": "",
        "generic_name": "alphacillin",
        "page_count": 3,
        "status": "ingested",
        "ingested_at": None,
        "failure_reason": None,
    }


def test_list_pages_keep_the_total(client: TestClient) -> None:
    body = client.get("/api/v1/documents", params={"page": 2, "page_size": 2}).json()

    assert body["total"] == 3
    assert [i["generic_name"] for i in body["items"]] == ["zetamab"]


def test_search_matches_brand_and_generic_name_case_insensitive(client: TestClient) -> None:
    by_brand = client.get("/api/v1/documents", params={"q": "ZET"}).json()
    by_generic = client.get("/api/v1/documents", params={"q": " cillin "}).json()

    assert [i["generic_name"] for i in by_brand["items"]] == ["zetamab"]
    assert by_generic["total"] == 1
    assert by_generic["items"][0]["generic_name"] == "alphacillin"


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"q": "x" * 201}]
)
def test_list_rejects_invalid_parameters(client: TestClient, params: dict[str, int | str]) -> None:
    assert client.get("/api/v1/documents", params=params).status_code == 422


def test_thumbnail_is_a_cacheable_png(client: TestClient) -> None:
    renderer = CountingRenderer()
    app.dependency_overrides[get_page_renderer] = lambda: renderer
    doc = DOCS[0]

    response = client.get(f"/api/v1/documents/{doc.id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["etag"] == f'"{doc.sha256}-w320"'
    assert "max-age" in response.headers["cache-control"]
    assert response.content.startswith(PNG_SIGNATURE)
    assert renderer.widths == [320]


def test_thumbnail_with_current_etag_is_not_modified(client: TestClient) -> None:
    renderer = CountingRenderer()
    app.dependency_overrides[get_page_renderer] = lambda: renderer
    doc = DOCS[0]

    response = client.get(
        f"/api/v1/documents/{doc.id}/thumbnail", headers={"If-None-Match": f'W/"{doc.sha256}-w320"'}
    )

    assert response.status_code == 304
    assert renderer.widths == []


def test_thumbnail_of_unknown_document_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/documents/{uuid.uuid4()}/thumbnail").status_code == 404


def test_thumbnail_of_missing_stored_object_is_404(client: TestClient, tmp_path: Path) -> None:
    FileSystemDocumentStore(tmp_path).delete(DOCS[0].storage_key)

    assert client.get(f"/api/v1/documents/{DOCS[0].id}/thumbnail").status_code == 404


def test_renderer_scales_page_one_to_the_width() -> None:
    png = PyMuPdfPageRenderer().render_first_page(make_pdf(pages=2, size=(600, 800)), 150)

    pixmap = pymupdf.Pixmap(png)
    assert png.startswith(PNG_SIGNATURE)
    assert pixmap.width == 150
    assert pixmap.height == 200


def test_download_is_an_attachment_named_by_title(client: TestClient, tmp_path: Path) -> None:
    doc = library_document("", "alpha cillin/é", "4" * 64)
    FileSystemDocumentStore(tmp_path).put(
        doc.storage_key, make_pdf(pages=2, size=(600, 800)), "application/pdf"
    )
    app.dependency_overrides[get_document_repository] = lambda: FakeDocumentRepository(doc)

    response = client.get(f"/api/v1/documents/{doc.id}/file", params={"download": 1})
    inline = client.get(f"/api/v1/documents/{doc.id}/file")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        f"attachment; filename=\"{doc.id}.pdf\"; filename*=UTF-8''alpha%20cillin%2F%C3%A9.pdf"
    )
    assert inline.headers["content-disposition"] == f'inline; filename="{doc.id}.pdf"'


def test_named_file_route_serves_the_same_pdf(client: TestClient) -> None:
    doc = DOCS[0]
    plain = client.get(f"/api/v1/documents/{doc.id}/file")

    named = client.get(f"/api/v1/documents/{doc.id}/file/Zeta XL.pdf")
    part = client.get(f"/api/v1/documents/{doc.id}/file/Zeta.pdf", headers={"Range": "bytes=0-4"})

    assert named.status_code == 200
    assert named.content == plain.content
    assert named.headers["content-disposition"] == plain.headers["content-disposition"]
    assert part.status_code == 206
    assert part.content == b"%PDF-"
