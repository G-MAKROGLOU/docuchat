"""Server-sent event types for the answer stream. Source of truth for the frontend types."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Stage = Literal["rewrite", "retrieve", "grade", "generate"]
RefusalReason = Literal["no_relevant_context", "no_valid_citation", "out_of_scope"]


class Event(BaseModel):
    # Fields with defaults (the "type" tag) are required in the exported schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class StatusEvent(Event):
    type: Literal["status"] = "status"
    stage: Stage
    message: str


class Source(Event):
    id: str
    document: str
    drug: str
    section: str
    page: int
    text: str


class SourcesEvent(Event):
    type: Literal["sources"] = "sources"
    items: list[Source]


class TokenEvent(Event):
    type: Literal["token"] = "token"
    text: str


class FinalEvent(Event):
    type: Literal["final"] = "final"
    answer: str
    citations: list[str]


class RefusalEvent(Event):
    type: Literal["refusal"] = "refusal"
    reason: RefusalReason


class ErrorEvent(Event):
    type: Literal["error"] = "error"
    message: str


StreamEvent = Annotated[
    StatusEvent | SourcesEvent | TokenEvent | FinalEvent | RefusalEvent | ErrorEvent,
    Field(discriminator="type"),
]


STREAM_EVENT_ADAPTER: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)
