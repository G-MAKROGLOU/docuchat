from typing import Protocol, cast

from fastapi import Request

from app.infrastructure.database import DatabaseStatus


class DatabaseProbe(Protocol):
    async def check(self) -> DatabaseStatus: ...


def get_database_probe(request: Request) -> DatabaseProbe:
    return cast(DatabaseProbe, request.app.state.database_probe)
