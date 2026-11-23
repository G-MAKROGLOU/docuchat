from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueueEntryResponse(BaseModel):
    set_id: str
    title: str
    status: Literal["queued", "added", "failed"]
    failure_reason: str | None
    created_at: datetime


class QueueResponse(BaseModel):
    items: list[QueueEntryResponse]
    total: int
    queued_total: int
    added_total: int
    failed_total: int
    labels_per_pass: int


class CatalogLabelResponse(BaseModel):
    set_id: str
    title: str
    version: int
    published: str


# A DailyMed set ID; the same rule as isSetId in the frontend.
SET_ID_PATTERN = r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$"


class AddLabelRequest(BaseModel):
    set_id: str = Field(pattern=SET_ID_PATTERN)
