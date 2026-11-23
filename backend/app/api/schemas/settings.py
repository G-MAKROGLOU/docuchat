from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.domain.runtime_settings import GraderMode, ReasoningEffort

MODEL_NAME = r"^[A-Za-z0-9._:/-]{1,100}$"


class SettingsBody(BaseModel):
    chunk_tokens: int = Field(ge=100, le=2000)
    overlap_tokens: int = Field(ge=0, le=500)
    top_k: int = Field(ge=5, le=50)
    embedding_model: str = Field(pattern=MODEL_NAME)
    chat_model: str = Field(pattern=MODEL_NAME)
    rewrite_model: str = Field(pattern=MODEL_NAME)
    grade_model: str = Field(pattern=MODEL_NAME)
    generate_model: str = Field(pattern=MODEL_NAME)
    reasoning_effort: ReasoningEffort
    grader_mode: GraderMode

    @model_validator(mode="after")
    def overlap_is_smaller_than_chunk(self) -> Self:
        if self.overlap_tokens >= self.chunk_tokens:
            raise ValueError("overlap_tokens must be smaller than chunk_tokens")
        return self


class SettingsResponse(SettingsBody):
    pass


class SettingsUpdate(SettingsBody):
    """A change of a chunk field or of the embedding model needs reingest_confirmed: it embeds
    every document again. Without embedding_model, the model stays as it is."""

    embedding_model: str | None = Field(default=None, pattern=MODEL_NAME)  # type: ignore[assignment]
    reingest_confirmed: bool = False


class SettingsOptions(BaseModel):
    """The values that the dropdowns offer. An empty chat_models: OpenRouter was not reachable."""

    chat_models: list[str]
    embedding_models: list[str]


class SettingsSaved(SettingsResponse):
    reingest_started: bool
