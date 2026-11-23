"""Settings that the user changes at run time, and their repository port. No framework imports."""

from dataclasses import dataclass
from typing import Literal, Protocol

GraderMode = Literal["off", "rule", "llm"]
ReasoningEffort = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    chunk_tokens: int
    overlap_tokens: int
    top_k: int
    embedding_model: str
    chat_model: str
    rewrite_model: str
    grade_model: str
    generate_model: str
    reasoning_effort: ReasoningEffort
    grader_mode: GraderMode


class InvalidSettingsError(ValueError):
    """A value that the settings cannot take, such as a model that is not offered."""


class SettingsConflictError(RuntimeError):
    """The save needs a confirmation, or the state of the library does not allow it now."""


class RuntimeSettingsRepository(Protocol):
    async def load(self) -> dict[str, object]:
        """The saved values by field name. Empty when nothing is saved."""
        ...

    async def save(self, values: dict[str, object]) -> None:
        """Replace the saved values by these."""
        ...
