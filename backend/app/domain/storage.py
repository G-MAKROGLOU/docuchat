"""Document storage port and key rules. No framework imports."""

from collections.abc import Iterator
from typing import Protocol
from uuid import UUID


class ObjectNotFoundError(LookupError):
    pass


def document_key(document_id: UUID, sha256: str) -> str:
    return f"documents/{document_id}/{sha256}.pdf"


class DocumentStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get_stream(self, key: str) -> Iterator[bytes]: ...

    def get_range(self, key: str, start: int, end: int) -> bytes:
        """Return bytes start..end, both inclusive, as in an HTTP Range header."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...
