from typing import Literal

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    connected: bool
    extensions: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: DatabaseHealth
