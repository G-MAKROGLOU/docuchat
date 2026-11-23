"""Conversations: stored chat turns and their repository port. No framework imports."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import MessageRole


@dataclass(frozen=True, slots=True)
class Turn:
    """One stored message. role is USER or ASSISTANT; citations are source IDs ("S1")."""

    id: UUID
    conversation_id: UUID
    role: MessageRole
    text: str
    created_at: datetime
    citations: tuple[str, ...] = ()


class ConversationRepository(Protocol):
    async def create(self) -> UUID: ...

    async def exists(self, conversation_id: UUID) -> bool: ...

    async def delete(self, conversation_id: UUID) -> bool:
        """Remove the conversation and its turns. True when it existed."""
        ...

    async def add_turn(
        self,
        conversation_id: UUID,
        role: MessageRole,
        text: str,
        citations: Sequence[str] = (),
    ) -> Turn: ...

    async def turns(self, conversation_id: UUID, limit: int | None = None) -> list[Turn]:
        """Oldest first. With a limit: the newest `limit` turns, still oldest first."""
        ...
