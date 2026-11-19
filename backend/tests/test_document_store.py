"""One test suite for every DocumentStore adapter. S3 runs when S3_TEST_ENDPOINT_URL is set."""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from botocore.config import Config

from app.domain.storage import DocumentStore, ObjectNotFoundError, document_key
from app.infrastructure.storage import FileSystemDocumentStore, S3DocumentStore

DATA = bytes(range(256)) * 1024  # 256 KiB, larger than one stream chunk


def _s3_store() -> S3DocumentStore:
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_TEST_ENDPOINT_URL"],
        region_name="us-east-1",
        aws_access_key_id=os.environ["S3_TEST_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_TEST_SECRET_KEY"],
        config=Config(s3={"addressing_style": "path"}),
    )
    store = S3DocumentStore(client, f"test-{uuid.uuid4().hex[:12]}", "us-east-1")
    store.ensure_bucket()
    return store


@pytest.fixture(params=["filesystem", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[DocumentStore]:
    if request.param == "filesystem":
        yield FileSystemDocumentStore(tmp_path)
        return
    if not os.environ.get("S3_TEST_ENDPOINT_URL"):
        pytest.skip("S3_TEST_ENDPOINT_URL is not set")
    yield _s3_store()


def test_put_then_exists_and_stream(store: DocumentStore) -> None:
    key = document_key(uuid.uuid4(), "a" * 64)
    assert not store.exists(key)

    store.put(key, DATA, "application/pdf")

    assert store.exists(key)
    assert b"".join(store.get_stream(key)) == DATA


def test_get_range_is_inclusive(store: DocumentStore) -> None:
    key = document_key(uuid.uuid4(), "b" * 64)
    store.put(key, DATA, "application/pdf")

    assert store.get_range(key, 0, 9) == DATA[0:10]
    assert store.get_range(key, 1000, 1999) == DATA[1000:2000]


def test_put_overwrites(store: DocumentStore) -> None:
    key = document_key(uuid.uuid4(), "c" * 64)
    store.put(key, b"old", "application/pdf")
    store.put(key, b"new", "application/pdf")

    assert b"".join(store.get_stream(key)) == b"new"


def test_delete_removes_and_is_idempotent(store: DocumentStore) -> None:
    key = document_key(uuid.uuid4(), "d" * 64)
    store.put(key, DATA, "application/pdf")

    store.delete(key)
    store.delete(key)

    assert not store.exists(key)


def test_missing_object_raises_not_found(store: DocumentStore) -> None:
    key = document_key(uuid.uuid4(), "e" * 64)

    with pytest.raises(ObjectNotFoundError):
        b"".join(store.get_stream(key))
    with pytest.raises(ObjectNotFoundError):
        store.get_range(key, 0, 1)


def test_document_key_format() -> None:
    document_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    assert document_key(document_id, "f" * 64) == f"documents/{document_id}/{'f' * 64}.pdf"


def test_filesystem_rejects_keys_outside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        FileSystemDocumentStore(tmp_path).put("../outside.pdf", b"x", "application/pdf")
