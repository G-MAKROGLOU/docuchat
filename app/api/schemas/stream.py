"""Server-sent event types for the answer stream.

KEEP IN SYNC with docuchat-frontend: src/lib/stream.ts. A change here needs the same change there.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Stage = Literal["rewrite", "retrieve", "grade", "generate"]
RefusalReason = Literal["no_relevant_context", "no_valid_citation", "out_of_scope"]


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    stage: Stage
    message: str


class Source(BaseModel):
    id: str
    document: str
    drug: str
    section: str
    page: int
    text: str


class SourcesEvent(BaseModel):
    type: Literal["sources"] = "sources"
    items: list[Source]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    answer: str
    citations: list[str]


class RefusalEvent(BaseModel):
    type: Literal["refusal"] = "refusal"
    reason: RefusalReason


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


StreamEvent = Annotated[
    StatusEvent | SourcesEvent | TokenEvent | FinalEvent | RefusalEvent | ErrorEvent,
    Field(discriminator="type"),
]
