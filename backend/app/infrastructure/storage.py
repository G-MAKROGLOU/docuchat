"""DocumentStore adapters: S3 (default) and local file system (tests, fallback)."""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings
from app.domain.storage import DocumentStore, ObjectNotFoundError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

CHUNK_SIZE = 64 * 1024
_NOT_FOUND = {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND


class S3DocumentStore:
    def __init__(self, client: "S3Client", bucket: str, region: str) -> None:
        self._client = client
        self._bucket = bucket
        self._region = region

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
            if self._region == "us-east-1":
                self._client.create_bucket(Bucket=self._bucket)
            else:
                self._client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region},  # type: ignore[typeddict-item]
                )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get_stream(self, key: str) -> Iterator[bytes]:
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        try:
            yield from body.iter_chunks(CHUNK_SIZE)
        finally:
            body.close()

    def get_range(self, key: str, start: int, end: int) -> bytes:
        try:
            response = self._client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}"
            )
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class FileSystemDocumentStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"Key escapes the storage root: {key}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file first, so a reader never sees a partial object.
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        Path(tmp).replace(path)

    def get_stream(self, key: str) -> Iterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                yield chunk

    def get_range(self, key: str, start: int, end: int) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        with path.open("rb") as handle:
            handle.seek(start)
            return handle.read(end - start + 1)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def build_document_store(settings: Settings) -> DocumentStore:
    # Settings validation guarantees these values; the checks narrow the types.
    if settings.storage_backend == "filesystem":
        if not settings.storage_fs_root:
            raise RuntimeError("STORAGE_FS_ROOT is not set")
        return FileSystemDocumentStore(Path(settings.storage_fs_root))
    if not (settings.s3_bucket and settings.s3_region):
        raise RuntimeError("S3_BUCKET and S3_REGION are not set")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value()
        if settings.s3_access_key
        else None,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value()
        if settings.s3_secret_key
        else None,
        # Emulators such as SeaweedFS need path-style addressing.
        config=Config(s3={"addressing_style": "path" if settings.s3_endpoint_url else "auto"}),
    )
    store = S3DocumentStore(client, settings.s3_bucket, settings.s3_region)
    store.ensure_bucket()
    return store
