"""Server-sent event types for the answer stream. Source of truth for the frontend types."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Stage = Literal["rewrite", "retrieve", "grade", "generate", "verify"]
RefusalReason = Literal[
    "no_relevant_context", "no_valid_citation", "out_of_scope", "drug_not_in_corpus"
]


class ContractModel(BaseModel):
    # Fields with defaults (the "type" tag) are required in the exported schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class StatusEvent(ContractModel):
    type: Literal["status"] = "status"
    stage: Stage
    message: str


class Source(ContractModel):
    id: str
    document: str
    drug: str
    section: str
    page: int
    text: str
    # The first words of the excerpt, to find it on the PDF page.
    anchor: str = ""


class SourcesEvent(ContractModel):
    type: Literal["sources"] = "sources"
    items: list[Source]


class TokenEvent(ContractModel):
    type: Literal["token"] = "token"
    text: str


class FinalEvent(ContractModel):
    type: Literal["final"] = "final"
    answer: str
    citations: list[str]


class RefusalEvent(ContractModel):
    type: Literal["refusal"] = "refusal"
    reason: RefusalReason
    # For drug_not_in_corpus: the medicines the library has.
    available_drugs: list[str] | None = None


class ClarifyEvent(ContractModel):
    """The drug name matches more than one label; a final event with the question follows."""

    type: Literal["clarify"] = "clarify"
    candidates: list[str]


class SuggestionsEvent(ContractModel):
    """Follow-up questions; sent after the final event of an answer or a reply."""

    type: Literal["suggestions"] = "suggestions"
    items: list[str]


class ErrorEvent(ContractModel):
    type: Literal["error"] = "error"
    message: str


StreamEvent = Annotated[
    StatusEvent
    | SourcesEvent
    | TokenEvent
    | FinalEvent
    | RefusalEvent
    | ClarifyEvent
    | SuggestionsEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


STREAM_EVENT_ADAPTER: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)
