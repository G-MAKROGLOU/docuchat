from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from app.api.schemas.stream import ContractModel
from app.application.chat import MAX_QUESTION_CHARS


class ConversationCreated(ContractModel):
    id: UUID


class AskRequest(BaseModel):
    # Spaces only count as empty: 422, not a stored empty turn.
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]


class TurnOut(ContractModel):
    id: UUID
    role: Literal["user", "assistant"]
    text: str
    citations: list[str]
    created_at: datetime


class ConversationOut(ContractModel):
    id: UUID
    turns: list[TurnOut]
