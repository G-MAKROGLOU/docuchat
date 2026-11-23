"""OpenAI-compatible fake model server for load tests. It costs nothing and answers each chat
graph step with a reply that step can use. Usage: uvicorn loadtest.fake_model:app --port 9000

Latency comes from FAKE_COMPLETE_SECONDS, FAKE_FIRST_TOKEN_SECONDS, FAKE_TOKENS_PER_SECOND,
FAKE_ANSWER_TOKENS and FAKE_EMBED_SECONDS."""

import asyncio
import base64
import hashlib
import json
import os
import re
import struct
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
_SOURCE_ID = re.compile(r"^\[(S\d+)\]", re.MULTILINE)


def _seconds(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _prompts() -> list[tuple[str, str]]:
    """(step, text) for every prompt file; the step is the file name before the version."""
    return [
        (p.name.split(".")[0], p.read_text(encoding="utf-8").strip())
        for p in sorted(PROMPT_DIR.glob("*.md"))
    ]


def _step(body: dict[str, Any], prompts: list[tuple[str, str]]) -> str:
    if body.get("response_format"):
        return "grade"
    if body.get("stream"):
        return "generate"
    system = next((m["content"] for m in body["messages"] if m["role"] == "system"), "")
    return next((step for step, text in prompts if system.startswith(text)), "unknown")


def _last_user(body: dict[str, Any]) -> str:
    return str(next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user"))


def _reply(step: str, body: dict[str, Any]) -> str:
    user = _last_user(body)
    if step == "intake":
        return json.dumps({"action": "search", "medicines": [], "query": user})
    if step == "grade":
        relevant = _SOURCE_ID.findall(user)
        return json.dumps({"relevant": relevant, "verdict": "sufficient", "feedback": ""})
    if step == "suggest":
        return json.dumps({"suggestions": ["What are the side effects?", "What is the dose?"]})
    # rewrite and anything unknown: the question itself.
    return user


def _answer(body: dict[str, Any], tokens: int) -> list[str]:
    ids = _SOURCE_ID.findall(_last_user(body))[:2] or ["S1"]
    filler = ["The", "label", "describes", "this", "topic", "in", "the", "cited", "section."]
    words = [filler[i % len(filler)] for i in range(max(tokens - len(ids), 1))]
    return [f"{w} " for w in words] + [f"[{i}] " for i in ids]


def _completion(model: str, content: str) -> dict[str, Any]:
    return {
        "id": "fake",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _chunk(model: str, delta: dict[str, str] | None, usage: dict[str, int] | None = None) -> bytes:
    choices = [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": None}]
    payload: dict[str, Any] = {
        "id": "fake",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
    }
    if usage is not None:
        payload["usage"] = usage
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


async def _stream(body: dict[str, Any]) -> AsyncIterator[bytes]:
    model = str(body.get("model", "fake"))
    words = _answer(body, int(_seconds("FAKE_ANSWER_TOKENS", 150)))
    rate = _seconds("FAKE_TOKENS_PER_SECOND", 60)
    await asyncio.sleep(_seconds("FAKE_FIRST_TOKEN_SECONDS", 1.0))
    yield _chunk(model, {"role": "assistant", "content": ""})
    for word in words:
        if rate > 0:
            await asyncio.sleep(1 / rate)
        yield _chunk(model, {"content": word})
    if body.get("stream_options", {}).get("include_usage"):
        usage = {
            "prompt_tokens": 1,
            "completion_tokens": len(words),
            "total_tokens": len(words) + 1,
        }
        yield _chunk(model, None, usage)
    yield b"data: [DONE]\n\n"


def _vector(text: str, size: int) -> list[float]:
    """A stable unit-free vector from the text hash, so the same text gets the same vector."""
    seed = hashlib.sha256(text.encode()).digest()
    return [(seed[i % len(seed)] - 127.5) / 127.5 for i in range(size)]


def build_app() -> FastAPI:
    app = FastAPI()
    prompts = _prompts()

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(request: Request) -> JSONResponse | StreamingResponse:
        body = await request.json()
        step = _step(body, prompts)
        if step == "generate":
            return StreamingResponse(_stream(body), media_type="text/event-stream")
        await asyncio.sleep(_seconds("FAKE_COMPLETE_SECONDS", 1.0))
        return JSONResponse(_completion(str(body.get("model", "fake")), _reply(step, body)))

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> JSONResponse:
        body = await request.json()
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        size = int(body.get("dimensions") or 1536)
        await asyncio.sleep(_seconds("FAKE_EMBED_SECONDS", 0.2))
        data = []
        for index, text in enumerate(texts):
            vector: list[float] | str = _vector(str(text), size)
            if body.get("encoding_format") == "base64":
                vector = base64.b64encode(struct.pack(f"<{size}f", *vector)).decode()
            data.append({"object": "embedding", "index": index, "embedding": vector})
        tokens = sum(len(str(t).split()) for t in texts)
        return JSONResponse(
            {
                "object": "list",
                "data": data,
                "model": body.get("model"),
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            }
        )

    return app


app = build_app()
