"""The shared cache adapter and the cached question embedder. The adapter tests run against a
real Redis when CACHE_TEST_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import pytest

from app.domain.entities import Message, MessageRole
from app.infrastructure.cache import KEY_PREFIX, CachedChatModel, CachedEmbedder, RedisCache
from tests.support.fakes_ports import FakeCache
from tests.support.tuning import SETTINGS


class CountingEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.documents: list[Sequence[str]] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents.append(texts)
        return [[0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1 * len(self.queries), 0.5]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_a_repeated_question_is_embedded_once_for_all_processes() -> None:
    inner, cache = CountingEmbedder(), FakeCache()
    # Two processes: two embedders on one shared cache.
    first = CachedEmbedder(inner, cache, "m/embed", 2, SETTINGS.cache_embedding_ttl_seconds)
    second = CachedEmbedder(inner, cache, "m/embed", 2, SETTINGS.cache_embedding_ttl_seconds)

    a = run(first.embed_query("lipitor dose"))
    b = run(second.embed_query("lipitor dose"))

    assert a == b
    assert a[1] == 0.5
    assert inner.queries == ["lipitor dose"]
    (key,) = cache.values
    assert key.startswith("embedding:m/embed:2:")
    assert "lipitor" not in key  # the question text is hashed, not stored in the key
    assert cache.ttls[key] > 0


def test_another_model_or_size_never_reuses_a_vector() -> None:
    inner, cache = CountingEmbedder(), FakeCache()

    run(
        CachedEmbedder(
            inner, cache, "m/embed", 2, SETTINGS.cache_embedding_ttl_seconds
        ).embed_query("dose")
    )
    run(
        CachedEmbedder(
            inner, cache, "m/other", 2, SETTINGS.cache_embedding_ttl_seconds
        ).embed_query("dose")
    )
    run(
        CachedEmbedder(
            inner, cache, "m/embed", 3, SETTINGS.cache_embedding_ttl_seconds
        ).embed_query("dose")
    )

    assert inner.queries == ["dose", "dose", "dose"]


def test_document_vectors_are_not_cached() -> None:
    inner, cache = CountingEmbedder(), FakeCache()

    run(
        CachedEmbedder(
            inner, cache, "m/embed", 2, SETTINGS.cache_embedding_ttl_seconds
        ).embed_documents(["a", "b"])
    )

    assert inner.documents == [["a", "b"]]
    assert cache.values == {}


def test_an_unreachable_cache_counts_as_a_miss() -> None:
    async def scenario() -> tuple[bytes | None, list[float]]:
        cache = RedisCache("redis://127.0.0.1:1/0", SETTINGS.cache_timeout_seconds)
        try:
            await cache.set("embedding:x", b"1", 60)
            embedder = CachedEmbedder(
                CountingEmbedder(), cache, "m/embed", 2, SETTINGS.cache_embedding_ttl_seconds
            )
            return await cache.get("embedding:x"), await embedder.embed_query("dose")
        finally:
            await cache.aclose()

    value, vector = run(scenario())

    assert value is None
    assert len(vector) == 2


class CountingChat:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str:
        self.calls += 1
        return f"reply {self.calls}"

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        self.calls += 1
        yield "streamed"


def conversation(question: str) -> list[Message]:
    return [Message(MessageRole.SYSTEM, "Rewrite v1"), Message(MessageRole.USER, question)]


def test_the_same_messages_give_the_same_reply_from_the_cache() -> None:
    inner, cache = CountingChat(), FakeCache()
    model = CachedChatModel(inner, cache, "m/rewrite:low", SETTINGS.cache_chat_ttl_seconds)

    async def scenario() -> list[str]:
        return [
            await model.complete(conversation("Lipitor in pregnancy?")),
            await model.complete(conversation("Lipitor in pregnancy?")),
            await model.complete(conversation("Crestor dose?")),
            await CachedChatModel(
                inner, cache, "m/other:low", SETTINGS.cache_chat_ttl_seconds
            ).complete(conversation("Crestor dose?")),
        ]

    assert run(scenario()) == ["reply 1", "reply 1", "reply 2", "reply 3"]
    assert inner.calls == 3


def test_structured_and_streamed_calls_are_not_cached() -> None:
    inner, cache = CountingChat(), FakeCache()
    model = CachedChatModel(inner, cache, "m/rewrite:low", SETTINGS.cache_chat_ttl_seconds)

    async def scenario() -> None:
        for _ in range(2):
            await model.complete(conversation("q"), json_schema={"type": "object"})
            _ = [t async for t in model.stream(conversation("q"))]

    run(scenario())

    assert inner.calls == 4
    assert cache.values == {}


requires_cache = pytest.mark.skipif(
    not os.environ.get("CACHE_TEST_URL"), reason="CACHE_TEST_URL is not set"
)


@requires_cache
def test_values_are_shared_and_expire() -> None:
    url = os.environ["CACHE_TEST_URL"]
    key = f"test:{uuid.uuid4()}"

    async def scenario() -> tuple[bytes | None, bytes | None, int]:
        writer, reader = (
            RedisCache(url, SETTINGS.cache_timeout_seconds),
            RedisCache(url, SETTINGS.cache_timeout_seconds),
        )
        try:
            missing = await reader.get(key)
            await writer.set(key, b"\x00png", 60)
            ttl = await reader._client.ttl(KEY_PREFIX + key)
            return missing, await reader.get(key), ttl
        finally:
            await writer.aclose()
            await reader.aclose()

    missing, found, ttl = run(scenario())

    assert missing is None
    assert found == b"\x00png"
    assert 0 < ttl <= 60
