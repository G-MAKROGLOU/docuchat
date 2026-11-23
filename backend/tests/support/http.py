"""HTTP helpers: the SSE event parser and a mocked OpenRouter stream."""

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from app.infrastructure.stream_chat import OpenRouterStreamChat

USAGE = {
    "prompt_tokens": 120,
    "completion_tokens": 7,
    "total_tokens": 127,
    "prompt_tokens_details": {"cached_tokens": 100},
    "completion_tokens_details": {"reasoning_tokens": 3},
}


def sse_events(text: str) -> list[dict[str, Any]]:
    """The JSON payloads of the "data:" blocks of a server-sent event body."""
    return [
        json.loads(block.removeprefix("data: "))
        for block in text.split("\n\n")
        if block.startswith("data: ")
    ]


def stream_chunk(content: str | None = None, **extra: object) -> str:
    delta = {} if content is None else {"content": content}
    body = {"id": "gen-1", "choices": [{"index": 0, "delta": delta}], **extra}
    return f"data: {json.dumps(body)}\n\n"


GOOD = (
    ": OPENROUTER PROCESSING\n\n"
    + stream_chunk("")
    + stream_chunk("Take it ")
    + stream_chunk("daily [S1].")
    + stream_chunk("", usage=USAGE)
    + "data: [DONE]\n\n"
)


def stream_model(handler: Callable[[httpx.Request], httpx.Response]) -> OpenRouterStreamChat:
    return OpenRouterStreamChat(
        name="llm-generate",
        model="vendor/model",
        base_url="https://router.test/api/v1",
        api_key=SecretStr("key"),
        max_tokens=64,
        reasoning_effort="low",
        transport=httpx.MockTransport(handler),
    )


def sse_response(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"content-type": "text/event-stream"})
