from typing import Protocol, cast

from fastapi import Request

from app.domain.documents import DocumentRepository
from app.domain.storage import DocumentStore
from app.infrastructure.database import DatabaseStatus


class DatabaseProbe(Protocol):
    async def check(self) -> DatabaseStatus: ...


def get_database_probe(request: Request) -> DatabaseProbe:
    return cast(DatabaseProbe, request.app.state.database_probe)


def get_document_repository(request: Request) -> DocumentRepository:
    return cast(DocumentRepository, request.app.state.document_repository)


def get_document_store(request: Request) -> DocumentStore:
    return cast(DocumentStore, request.app.state.document_store)
