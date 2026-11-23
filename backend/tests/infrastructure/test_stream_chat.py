import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.infrastructure.stream_chat import ModelStreamError, OpenRouterStreamChat
from tests.support.http import GOOD, sse_response, stream_chunk, stream_model


async def collect(m: OpenRouterStreamChat, **kwargs: object) -> list[str]:
    return [c.text async for c in m.astream([("user", "dose?")], **kwargs)]  # type: ignore[arg-type]


def test_the_text_chunks_arrive_in_order_and_comments_are_skipped() -> None:
    texts = asyncio.run(collect(stream_model(lambda request: sse_response(GOOD))))

    assert "".join(texts) == "Take it daily [S1]."


def test_the_request_asks_for_a_stream_with_usage_and_the_settings() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return sse_response(GOOD)

    asyncio.run(collect(stream_model(handler)))

    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://router.test/api/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer key"
    assert body["model"] == "vendor/model"
    assert body["messages"] == [{"role": "user", "content": "dose?"}]
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["max_tokens"] == 64
    assert body["reasoning"] == {"effort": "low"}


class Recorder(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.metadata: dict[str, object] = {}
        self.invocation_params: dict[str, object] = {}
        self.result: LLMResult | None = None

    async def on_chat_model_start(self, serialized, messages, *, metadata=None, **kwargs):  # type: ignore[no-untyped-def]
        self.metadata = dict(metadata or {})
        self.invocation_params = dict(kwargs.get("invocation_params") or {})

    async def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        self.result = response


def test_the_trace_gets_the_model_name_and_the_usage() -> None:
    recorder = Recorder()

    asyncio.run(
        collect(stream_model(lambda request: sse_response(GOOD)), config={"callbacks": [recorder]})
    )

    assert recorder.metadata["ls_model_name"] == "vendor/model"
    assert recorder.invocation_params["max_completion_tokens"] == 64
    assert recorder.result is not None
    generation = recorder.result.generations[0][0]
    assert isinstance(generation, ChatGeneration)
    message = generation.message
    assert isinstance(message, AIMessage)
    assert message.content == "Take it daily [S1]."
    assert message.usage_metadata == {
        "input_tokens": 120,
        "output_tokens": 7,
        "total_tokens": 127,
        "input_token_details": {"cache_read": 100},
        "output_token_details": {"reasoning": 3},
    }


def test_an_error_chunk_fails_the_stream() -> None:
    error = stream_chunk("", error={"code": 502, "message": "Provider disconnected"})

    with pytest.raises(ModelStreamError, match="Provider disconnected"):
        asyncio.run(
            collect(stream_model(lambda request: sse_response(stream_chunk("Take ") + error)))
        )


def test_a_server_error_before_any_text_is_tried_once_more() -> None:
    replies = iter([sse_response('{"error": "busy"}', status=503), sse_response(GOOD)])

    assert "".join(asyncio.run(collect(stream_model(lambda request: next(replies))))) == (
        "Take it daily [S1]."
    )


def test_a_second_server_error_fails_with_the_status() -> None:
    with pytest.raises(ModelStreamError, match="429"):
        asyncio.run(
            collect(stream_model(lambda request: sse_response('{"error": "limit"}', status=429)))
        )


def test_a_client_error_is_not_tried_again() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return sse_response('{"error": "bad model"}', status=400)

    with pytest.raises(ModelStreamError, match="400"):
        asyncio.run(collect(stream_model(handler)))
    assert len(calls) == 1


class BreaksAfterFirstChunk(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield stream_chunk("Take ").encode()
        raise httpx.ReadError("connection reset")


def test_a_network_error_after_text_fails_without_a_second_try() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, stream=BreaksAfterFirstChunk())

    texts: list[str] = []

    async def scenario() -> None:
        async for c in stream_model(handler).astream([("user", "dose?")]):
            texts.append(c.text)

    with pytest.raises(ModelStreamError, match="ReadError"):
        asyncio.run(scenario())
    assert calls == [1]
    assert texts == ["Take "]


def test_a_stream_that_ends_before_done_fails() -> None:
    cut = stream_chunk("Take ") + stream_chunk("it")

    with pytest.raises(ModelStreamError, match="ended early"):
        asyncio.run(collect(stream_model(lambda request: sse_response(cut))))
