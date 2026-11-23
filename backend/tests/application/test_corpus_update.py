import asyncio
import hashlib
import uuid
from pathlib import Path

from app.application.corpus_update import check_for_updates
from app.domain.documents import Document, DocumentStatus
from app.domain.storage import document_key, label_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.support.factories import make_document
from tests.support.fakes_ingestion import SPL, FakeDocumentRepository, FakeSource
from tests.support.tuning import CHUNK_BYTES, SETTINGS

OLD_PDF = b"%PDF-1.7 old"
NEW_PDF = b"%PDF-1.7 new"
NEW_SPL = SPL + b"<!-- version 2 -->"


def stored_document(store: FileSystemDocumentStore) -> Document:
    doc_id = uuid.uuid4()
    sha = hashlib.sha256(OLD_PDF).hexdigest()
    document = make_document(
        "Alpha",
        "alphamab",
        document_id=doc_id,
        manufacturer="M",
        source_id="s1",
        sha=sha,
        size_bytes=len(OLD_PDF),
        status=DocumentStatus.INGESTED,
        page_count=3,
    )
    store.put(document.storage_key, OLD_PDF, "application/pdf")
    store.put(label_key(doc_id), SPL, "application/xml")
    return document


def test_an_unchanged_label_is_left_alone(tmp_path: Path) -> None:
    store = FileSystemDocumentStore(tmp_path, CHUNK_BYTES)
    doc = stored_document(store)
    repo = FakeDocumentRepository(doc)
    source = FakeSource()

    report = asyncio.run(
        check_for_updates(
            source, store, repo, delay_seconds=0, concurrency=SETTINGS.update_check_concurrency
        )
    )

    assert (report.checked, report.updated, report.failed) == (1, 0, 0)
    assert source.calls == ["s1.xml"]
    assert asyncio.run(repo.get(doc.id)) == doc


def test_a_changed_label_is_stored_again_and_set_back_to_stored(tmp_path: Path) -> None:
    store = FileSystemDocumentStore(tmp_path, CHUNK_BYTES)
    doc = stored_document(store)
    repo = FakeDocumentRepository(doc)
    source = FakeSource(payloads={"s1": NEW_PDF}, labels={"s1": NEW_SPL})

    report = asyncio.run(
        check_for_updates(
            source, store, repo, delay_seconds=0, concurrency=SETTINGS.update_check_concurrency
        )
    )

    updated = asyncio.run(repo.get(doc.id))
    new_sha = hashlib.sha256(NEW_PDF).hexdigest()
    assert (report.checked, report.updated, report.failed) == (1, 1, 0)
    assert updated is not None
    assert updated.status is DocumentStatus.STORED
    assert updated.sha256 == new_sha
    assert updated.storage_key == document_key(doc.id, new_sha)
    assert b"".join(store.get_stream(updated.storage_key)) == NEW_PDF
    assert b"".join(store.get_stream(label_key(doc.id))) == NEW_SPL
    assert not store.exists(doc.storage_key)


def test_a_failed_fetch_is_counted_and_does_not_stop_the_check(tmp_path: Path) -> None:
    store = FileSystemDocumentStore(tmp_path, CHUNK_BYTES)
    doc = stored_document(store)
    second = stored_document(store)
    repo = FakeDocumentRepository(doc, second)
    source = FakeSource(labels={"s1": b"not an spl document"})

    report = asyncio.run(
        check_for_updates(
            source, store, repo, delay_seconds=0, concurrency=SETTINGS.update_check_concurrency
        )
    )

    assert report.checked == 2
    assert report.failed == 2
    assert report.updated == 0
