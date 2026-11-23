import asyncio
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_document_repository,
    get_label_catalog,
    get_label_queue_repository,
)
from app.application.label_queue import (
    LabelKnownError,
    LabelNotFoundError,
    QueueContext,
    add_label,
    process_queue,
)
from app.domain.documents import DocumentStatus
from app.domain.label_queue import (
    CatalogLabel,
    LabelMetadata,
    QueueStatus,
)
from app.infrastructure.spl_parser import SplXmlParser
from app.infrastructure.storage import FileSystemDocumentStore
from app.main import app
from tests.support.factories import make_document
from tests.support.fakes_ingestion import (
    CATALOG_LABEL,
    KNOWN_SET_ID,
    FakeCatalog,
    FakeDocumentRepository,
    FakeQueue,
    FakeSource,
)
from tests.support.tuning import CHUNK_BYTES, SETTINGS

OTHER = "10a7ba02-42d6-4cae-8904-b256e2da5496"


class FakeReader:
    def metadata(self, data: bytes) -> LabelMetadata:
        return LabelMetadata("Lipitor", "atorvastatin", "Viatris")


def test_a_label_is_queued_after_the_catalogue_confirms_it() -> None:
    queue = FakeQueue()
    documents = cast(Any, FakeDocumentRepository())

    label = asyncio.run(add_label(FakeCatalog(), queue, documents, f" {KNOWN_SET_ID.upper()} "))

    assert label == CATALOG_LABEL
    assert list(queue.entries) == [KNOWN_SET_ID]


@pytest.mark.parametrize("set_id", [OTHER, "not-a-set-id"])
def test_a_label_the_catalogue_does_not_know_is_refused(set_id: str) -> None:
    queue = FakeQueue()

    with pytest.raises(LabelNotFoundError):
        asyncio.run(add_label(FakeCatalog(), queue, cast(Any, FakeDocumentRepository()), set_id))

    assert queue.entries == {}


def test_a_queued_label_is_refused_a_second_time() -> None:
    queue = FakeQueue()
    documents = cast(Any, FakeDocumentRepository())
    asyncio.run(add_label(FakeCatalog(), queue, documents, KNOWN_SET_ID))

    with pytest.raises(LabelKnownError):
        asyncio.run(add_label(FakeCatalog(), queue, documents, KNOWN_SET_ID))


def test_the_pass_downloads_queued_labels_and_marks_them(tmp_path: Path) -> None:
    queue = FakeQueue()
    repo = FakeDocumentRepository()
    asyncio.run(queue.add(KNOWN_SET_ID, "t"))
    asyncio.run(queue.add(OTHER, "t"))
    context = QueueContext(
        FakeSource(),
        FakeReader(),
        FileSystemDocumentStore(tmp_path, CHUNK_BYTES),
        cast(Any, repo),
        SETTINGS.failure_reason_max_chars,
    )

    report = asyncio.run(process_queue(queue, context, limit=1, delay_seconds=0))

    assert (report.added, report.failed) == (1, 0)
    assert queue.entries[KNOWN_SET_ID].status is QueueStatus.ADDED
    assert queue.entries[OTHER].status is QueueStatus.QUEUED
    document = asyncio.run(repo.find_by_source_id(KNOWN_SET_ID))
    assert document is not None
    assert (document.brand_name, document.manufacturer) == ("Lipitor", "Viatris")


def test_a_failed_download_is_marked_with_a_reason(tmp_path: Path) -> None:
    queue = FakeQueue()
    asyncio.run(queue.add("broken", "t"))
    context = QueueContext(
        FakeSource(),
        FakeReader(),
        FileSystemDocumentStore(tmp_path, CHUNK_BYTES),
        cast(Any, FakeDocumentRepository()),
        SETTINGS.failure_reason_max_chars,
    )

    report = asyncio.run(
        process_queue(queue, context, delay_seconds=0, limit=SETTINGS.label_queue_batch)
    )

    assert (report.added, report.failed) == (0, 1)
    assert queue.entries["broken"].status is QueueStatus.FAILED
    assert queue.entries["broken"].failure_reason == "The download failed. See the API log."


SPL_NAMES = b"""<document xmlns="urn:hl7-org:v3">
 <author><assignedEntity><representedOrganization><name>Viatris</name>
 </representedOrganization></assignedEntity></author>
 <component><structuredBody><component><section><subject><manufacturedProduct>
  <manufacturedProduct><name>Lipitor</name>
   <formCode code="C42927" displayName="TABLET, FILM COATED"/><asEntityWithGeneric><genericMedicine>
   <name>atorvastatin calcium</name></genericMedicine></asEntityWithGeneric>
  </manufacturedProduct></manufacturedProduct></subject></section></component>
 </structuredBody></component></document>"""


def test_the_parser_reads_product_and_manufacturer_names_and_the_dosage_form() -> None:
    assert SplXmlParser().metadata(SPL_NAMES) == LabelMetadata(
        "Lipitor", "atorvastatin calcium", "Viatris", "TABLET, FILM COATED"
    )


def test_the_api_adds_lists_and_removes_a_label(label_client: TestClient) -> None:
    added = label_client.post("/api/v1/labels", json={"set_id": KNOWN_SET_ID})
    listed = label_client.get("/api/v1/labels").json()
    removed = label_client.delete(f"/api/v1/labels/{KNOWN_SET_ID}")

    assert added.status_code == 201
    assert added.json()["title"] == CATALOG_LABEL.title
    assert [item["set_id"] for item in listed["items"]] == [KNOWN_SET_ID]
    assert listed["labels_per_pass"] == 50
    assert listed["added_total"] == 0
    assert (listed["total"], listed["queued_total"], listed["failed_total"]) == (1, 1, 0)
    assert removed.status_code == 204
    assert label_client.get("/api/v1/labels").json()["items"] == []


def test_the_api_rejects_a_request_without_a_set_id(label_client: TestClient) -> None:
    assert label_client.post("/api/v1/labels", json={}).status_code == 422


def test_the_api_refuses_unknown_and_double_labels(label_client: TestClient) -> None:
    assert label_client.post("/api/v1/labels", json={"set_id": OTHER}).status_code == 404
    label_client.post("/api/v1/labels", json={"set_id": KNOWN_SET_ID})
    assert label_client.post("/api/v1/labels", json={"set_id": KNOWN_SET_ID}).status_code == 409
    assert label_client.delete(f"/api/v1/labels/{OTHER}").status_code == 404
    assert label_client.delete(f"/api/v1/labels/{KNOWN_SET_ID.upper()}").status_code == 204


def test_the_api_reports_a_catalogue_that_cannot_be_reached(label_client: TestClient) -> None:
    class Down:
        def lookup(self, set_id: str) -> CatalogLabel | None:
            raise OSError("network down")

        def search(self, drug_name: str, limit: int) -> list[CatalogLabel]:
            raise OSError("network down")

    app.dependency_overrides[get_label_catalog] = Down

    assert label_client.get("/api/v1/labels/search", params={"q": "lipitor"}).status_code == 502
    assert label_client.post("/api/v1/labels", json={"set_id": KNOWN_SET_ID}).status_code == 502


def test_a_label_with_a_stored_pdf_is_marked_with_that_reason(tmp_path: Path) -> None:
    queue = FakeQueue()
    repo = FakeDocumentRepository()
    asyncio.run(queue.add(KNOWN_SET_ID, "t"))
    asyncio.run(queue.add(OTHER, "t"))
    context = QueueContext(
        FakeSource(payloads={OTHER: b"%PDF-1.7 " + KNOWN_SET_ID.encode()}),
        FakeReader(),
        FileSystemDocumentStore(tmp_path, CHUNK_BYTES),
        cast(Any, repo),
        SETTINGS.failure_reason_max_chars,
    )

    asyncio.run(process_queue(queue, context, delay_seconds=0, limit=SETTINGS.label_queue_batch))

    assert queue.entries[OTHER].status is QueueStatus.FAILED
    assert (
        queue.entries[OTHER].failure_reason == "A label with the same PDF is already in the corpus."
    )


def test_the_api_searches_the_catalogue(label_client: TestClient) -> None:
    response = label_client.get("/api/v1/labels/search", params={"q": "lipitor"})

    assert response.status_code == 200
    assert response.json()[0]["set_id"] == KNOWN_SET_ID


def test_the_search_leaves_out_labels_in_the_queue(label_client: TestClient) -> None:
    assert len(label_client.get("/api/v1/labels/search", params={"q": "lipitor"}).json()) == 1

    label_client.post("/api/v1/labels", json={"set_id": KNOWN_SET_ID})

    assert label_client.get("/api/v1/labels/search", params={"q": "lipitor"}).json() == []


def test_the_api_lists_the_queue_in_pages_with_the_totals() -> None:
    queue = FakeQueue()
    for number in range(5):
        asyncio.run(queue.add(f"set-{number}", f"title {number}"))
    asyncio.run(queue.mark("set-0", QueueStatus.ADDED, None))
    app.dependency_overrides[get_label_queue_repository] = lambda: queue
    client = TestClient(app)

    second = client.get("/api/v1/labels", params={"page": 2, "page_size": 2}).json()
    default = client.get("/api/v1/labels").json()
    too_big = client.get("/api/v1/labels", params={"page_size": 101})

    assert [i["set_id"] for i in second["items"]] == ["set-3", "set-4"]
    assert (second["total"], second["queued_total"], second["added_total"]) == (5, 4, 1)
    assert len(default["items"]) == 5
    assert default["items"][-1]["status"] == "added"
    assert too_big.status_code == 422


def test_the_search_leaves_out_labels_in_the_library() -> None:
    doc_id = uuid.uuid4()
    in_library = make_document(
        "Lipitor",
        "atorvastatin",
        document_id=doc_id,
        source_id=KNOWN_SET_ID,
        storage_key=f"documents/{doc_id}.pdf",
        size_bytes=10,
        status=DocumentStatus.INGESTED,
    )
    app.dependency_overrides[get_label_queue_repository] = FakeQueue
    app.dependency_overrides[get_label_catalog] = FakeCatalog
    app.dependency_overrides[get_document_repository] = lambda: FakeDocumentRepository(in_library)
    found = TestClient(app).get("/api/v1/labels/search", params={"q": "lipitor"}).json()

    assert found == []
