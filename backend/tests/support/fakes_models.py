"""Chat model fakes: scripted completions and streamed tokens per model role."""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from app.domain.entities import Message, ModelRole

# A grade reply that keeps no excerpt.
NOTHING = '{"relevant": [], "verdict": "insufficient", "feedback": "No dose."}'


class FakeModel:
    def __init__(self, completions: Sequence[str] = (), tokens: Sequence[str] = ()) -> None:
        self._completions = list(completions)
        self._tokens = list(tokens)
        self.calls: list[list[Message]] = []
        self.schemas: list[Mapping[str, object] | None] = []

    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str:
        self.calls.append(list(messages))
        self.schemas.append(json_schema)
        return self._completions.pop(0)

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        for token in self._tokens:
            yield token


class BrokenModel(FakeModel):
    async def complete(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("provider down")


class FakeModels:
    def __init__(self, **by_role: FakeModel) -> None:
        self.by_role = {ModelRole(role): model for role, model in by_role.items()}

    def for_role(self, role: ModelRole) -> FakeModel:
        return self.by_role[role]


def search_models(
    grade: str | Sequence[str] = '{"relevant": ["S1"]}', tokens: Sequence[str] = ()
) -> FakeModels:
    grades = [grade] if isinstance(grade, str) else list(grade)
    return FakeModels(
        chat=FakeModel(['{"action": "search"}']),
        rewrite=FakeModel(["query", "query again"]),
        grade=FakeModel(grades),
        generate=FakeModel(tokens=tokens),
    )
