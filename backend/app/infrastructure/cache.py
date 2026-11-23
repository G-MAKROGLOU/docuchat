"""The shared cache on Redis, and the cached question embedder.

Every API process and the worker use the same cache, so a value is computed once for all of
them. The cache is optional for correctness: an error is logged and counts as a miss."""

import hashlib
import json
import logging
from array import array
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import cast

import redis.asyncio as redis

from app.domain.entities import Message
from app.domain.ports import Cache, ChatModel, Embedder
from app.infrastructure.metrics import CACHE_REQUESTS

logger = logging.getLogger(__name__)

# All keys start with this; the version changes when a stored value changes its format.
KEY_PREFIX = "docuchat:v1:"
# A slow cache must not slow a request much: after this, the value is computed instead.
TIMEOUT_SECONDS = 0.5
# A question vector of one model never changes; the memory limit evicts old ones first.
EMBEDDING_TTL_SECONDS = 30 * 24 * 3600
# A model reply for the same messages, model and effort.
CHAT_TTL_SECONDS = 7 * 24 * 3600


def _kind(key: str) -> str:
    return key.removeprefix(KEY_PREFIX).split(":", 1)[0]


class RedisCache:
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(
            url, socket_timeout=TIMEOUT_SECONDS, socket_connect_timeout=TIMEOUT_SECONDS
        )

    async def get(self, key: str) -> bytes | None:
        try:
            # decode_responses is off, so the client gives bytes.
            value = cast("bytes | None", await self._client.get(KEY_PREFIX + key))
        except Exception as exc:  # any cache fault is a miss, never a failed request
            CACHE_REQUESTS.labels(_kind(key), "error").inc()
            logger.warning("cache read failed", extra={"error": repr(exc)})
            return None
        CACHE_REQUESTS.labels(_kind(key), "miss" if value is None else "hit").inc()
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        try:
            await self._client.set(KEY_PREFIX + key, value, ex=ttl_seconds)
        except Exception as exc:  # any cache fault is a miss, never a failed request
            CACHE_REQUESTS.labels(_kind(key), "error").inc()
            logger.warning("cache write failed", extra={"error": repr(exc)})

    async def aclose(self) -> None:
        await self._client.aclose()


# One client (and connection pool) per URL in this process.
_caches: dict[str, RedisCache] = {}


def shared_cache(url: str) -> RedisCache:
    if url not in _caches:
        _caches[url] = RedisCache(url)
    return _caches[url]


async def close_caches() -> None:
    """Closes the cache connections; called when the process stops."""
    for cache in _caches.values():
        await cache.aclose()
    _caches.clear()


class CachedEmbedder:
    """Question vectors from the shared cache; document vectors always from the model."""

    def __init__(self, inner: Embedder, cache: Cache, model: str, dimensions: int) -> None:
        self._inner = inner
        self._cache = cache
        self._namespace = f"embedding:{model}:{dimensions}:"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        key = self._namespace + hashlib.sha256(text.encode()).hexdigest()
        if (cached := await self._cache.get(key)) is not None:
            return array("f", cached).tolist()
        # 4-byte floats, as in the pgvector column; a miss returns the same values as a hit.
        vector = array("f", await self._inner.embed_query(text))
        await self._cache.set(key, vector.tobytes(), EMBEDDING_TTL_SECONDS)
        return vector.tolist()


class CachedChatModel:
    """Plain replies from the shared cache when the messages are the same, so a repeated
    question gets the same search query. Structured and streamed replies are not cached."""

    def __init__(self, inner: ChatModel, cache: Cache, name: str) -> None:
        self._inner = inner
        self._cache = cache
        self._namespace = f"chat:{name}:"

    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str:
        if json_schema is not None:
            return await self._inner.complete(messages, json_schema=json_schema)
        text = json.dumps([[m.role.value, m.content] for m in messages])
        key = self._namespace + hashlib.sha256(text.encode()).hexdigest()
        if (cached := await self._cache.get(key)) is not None:
            return cached.decode()
        reply = await self._inner.complete(messages)
        await self._cache.set(key, reply.encode(), CHAT_TTL_SECONDS)
        return reply

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        return self._inner.stream(messages)
