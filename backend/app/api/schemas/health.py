from typing import Literal

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    connected: bool
    extensions: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: DatabaseHealth


class ReadyCheck(BaseModel):
    name: str
    ok: bool
    # A failed optional check is a warning; the service stays ready.
    required: bool
    detail: str | None
    duration_ms: float


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadyCheck]
