"""LLM judge for answer correctness: one call compares the answer with the
reference answer. A reply that does not parse gives no verdict, so it does not count."""

import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.domain.entities import Message, MessageRole


class Completer(Protocol):
    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str: ...


PROMPT = """You grade an answer about a drug label against a reference answer.
The answer is correct when it states the facts of the reference answer (doses, units,
conditions) without a contradiction. Extra correct detail and citation markers like [S1] are
fine. Missing a key fact of the reference, or a wrong number, makes it incorrect.
Reply with JSON only: {"correct": true or false, "reason": "<one short sentence>"}."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"correct": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["correct", "reason"],
    "additionalProperties": False,
}


async def judge(
    model: Completer, question: str, reference: str, answer: str
) -> tuple[bool | None, str]:
    messages = [
        Message(MessageRole.SYSTEM, PROMPT),
        Message(
            MessageRole.USER,
            f"Question: {question}\n\nReference answer: {reference}\n\nAnswer: {answer}",
        ),
    ]
    reply = await model.complete(messages, json_schema=SCHEMA)
    try:
        parsed = json.loads(reply)
        return bool(parsed["correct"]), str(parsed.get("reason", ""))
    except (ValueError, KeyError, TypeError):
        return None, f"judge reply did not parse: {reply[:80]!r}"
