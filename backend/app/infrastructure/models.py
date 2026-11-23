"""The one factory for model and embedding clients (OpenRouter through LangChain)."""

import asyncio
import json
import logging
import urllib.request
from collections.abc import AsyncIterator, Mapping, Sequence

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from app.config import Settings
from app.domain.entities import Message, ModelRole
from app.domain.ports import ChatModel, ChatModelProvider, Embedder
from app.infrastructure.cache import CachedChatModel, CachedEmbedder, shared_cache
from app.infrastructure.metrics import LLM_METRICS, SEARCH_SECONDS
from app.infrastructure.stream_chat import OpenRouterStreamChat

logger = logging.getLogger(__name__)

# Embedding models that were checked to return 1536 values when asked for dimensions=1536, the
# size of the vector column. Others return another size or reject the request.
EMBEDDING_CHOICES = (
    "openai/text-embedding-3-small",
    "openai/text-embedding-3-large",
    "google/gemini-embedding-001",
    "google/gemini-embedding-2",
    "cohere/embed-5-fast",
    "cohere/embed-5-pro",
    "qwen/qwen3-embedding-4b",
    "qwen/qwen3-embedding-8b",
)
# Model clients of this process, shared across settings changes (see ModelFactory).
_chat_clients: dict[tuple[object, ...], "OpenRouterChatModel"] = {}
_embedders: dict[tuple[object, ...], CachedEmbedder] = {}


class OpenRouterEmbedder:
    def __init__(self, client: OpenAIEmbeddings, dimensions: int) -> None:
        self._client = client
        self._dimensions = dimensions

    def _checked(self, vectors: list[list[float]]) -> list[list[float]]:
        if any(len(v) != self._dimensions for v in vectors):
            raise ValueError(f"Embedding size differs from EMBEDDING_DIMENSIONS={self._dimensions}")
        return vectors

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._checked(await self._client.aembed_documents(list(texts)))

    async def embed_query(self, text: str) -> list[float]:
        with SEARCH_SECONDS.labels("embed_query").time():
            return self._checked([await self._client.aembed_query(text)])[0]


class OpenRouterChatModel:
    def __init__(self, client: ChatOpenAI, streamer: OpenRouterStreamChat) -> None:
        self._client = client
        # Streams without the OpenAI SDK objects; see stream_chat.
        self._streamer = streamer

    @staticmethod
    def _payload(messages: Sequence[Message]) -> list[dict[str, str]]:
        return [{"role": m.role.value, "content": m.content} for m in messages]

    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str:
        if json_schema is None:
            return (await self._client.ainvoke(self._payload(messages))).text
        # No provider.require_parameters: Opus 5.5 rejects `temperature`, so no endpoint would
        # match. The caller must still handle a reply that does not follow the schema.
        reply = await self._client.ainvoke(
            self._payload(messages),
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "reply", "strict": True, "schema": dict(json_schema)},
            },
        )
        return reply.text

    async def aclose(self) -> None:
        await self._streamer.aclose()
        await self._client.root_async_client.close()

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        async for chunk in self._streamer.astream(self._payload(messages)):
            if chunk.text:
                yield chunk.text


class RoleModels:
    def __init__(self, models: Mapping[ModelRole, ChatModel]) -> None:
        self._models = models

    def for_role(self, role: ModelRole) -> ChatModel:
        return self._models[role]


class ModelFactory:
    def __init__(self, settings: Settings, reasoning_effort: str = "low") -> None:
        self._settings = settings
        self._reasoning_effort = reasoning_effort

    def chat_models(self) -> ChatModelProvider:
        s = self._settings
        names = {
            ModelRole.CHAT: s.llm_chat_model,
            ModelRole.REWRITE: s.llm_rewrite_model,
            ModelRole.GRADE: s.llm_grade_model,
            ModelRole.GENERATE: s.llm_generate_model,
        }
        models: dict[ModelRole, ChatModel] = {
            role: self._chat_model(role, name) for role, name in names.items()
        }
        # The same question and conversation give the same search query, so its vector and
        # the search are reused. The intake (chat role) also writes the query.
        cache = shared_cache(s)
        for role in (ModelRole.CHAT, ModelRole.REWRITE):
            models[role] = CachedChatModel(
                models[role],
                cache,
                f"{role.value}:{names[role]}:{self._reasoning_effort}",
                s.cache_chat_ttl_seconds,
            )
        return RoleModels(models)

    def _chat_model(self, role: ModelRole, name: str) -> OpenRouterChatModel:
        """One client pair per role and model in this process: a settings change builds clients
        only for the roles it changes, so the HTTP connections stay in use."""
        s = self._settings
        # Output limit in tokens; the reasoning effort counts toward it too.
        max_tokens = {
            ModelRole.CHAT: s.max_output_tokens_chat,
            ModelRole.REWRITE: s.max_output_tokens_rewrite,
            ModelRole.GRADE: s.max_output_tokens_grade,
            ModelRole.GENERATE: s.max_output_tokens_generate,
        }[role]
        key = (role, name, self._reasoning_effort, s.openrouter_base_url)
        if key not in _chat_clients:
            _chat_clients[key] = OpenRouterChatModel(
                ChatOpenAI(
                    # The generation name in traces.
                    name=f"llm-{role.value}",
                    model=name,
                    base_url=s.openrouter_base_url,
                    api_key=SecretStr(s.openrouter_api_key.get_secret_value()),
                    temperature=0,
                    max_tokens=max_tokens,
                    # Then the turn fails with an error event.
                    max_retries=s.chat_model_max_retries,
                    timeout=s.model_timeout_seconds,
                    # Claude 5.5 thinks at medium effort by default, which delays the first
                    # token. Opus 5.5 cannot turn thinking off, so the default is the lowest.
                    extra_body={"reasoning": {"effort": self._reasoning_effort}},
                    callbacks=[LLM_METRICS],
                ),
                OpenRouterStreamChat(
                    name=f"llm-{role.value}",
                    model=name,
                    base_url=s.openrouter_base_url,
                    api_key=SecretStr(s.openrouter_api_key.get_secret_value()),
                    max_tokens=max_tokens,
                    reasoning_effort=self._reasoning_effort,
                    timeout=s.model_timeout_seconds,
                    max_retries=s.chat_model_max_retries,
                    first_backoff_seconds=s.stream_first_backoff_seconds,
                    max_backoff_seconds=s.stream_max_backoff_seconds,
                    callbacks=[LLM_METRICS],
                ),
            )
        return _chat_clients[key]

    def embedder(self) -> Embedder:
        s = self._settings
        cache_url = s.cache_url.get_secret_value()
        key = (s.embedding_model, s.embedding_dimensions, s.openrouter_base_url, cache_url)
        if key not in _embedders:
            client = OpenAIEmbeddings(
                model=s.embedding_model,
                dimensions=s.embedding_dimensions,
                openai_api_base=s.openrouter_base_url,
                openai_api_key=SecretStr(s.openrouter_api_key.get_secret_value()),
                # OpenRouter takes text input; skip the client-side token pre-split.
                check_embedding_ctx_length=False,
                chunk_size=s.embedding_batch_size,
                max_retries=s.embedding_max_retries,
                request_timeout=s.model_timeout_seconds,
            )
            _embedders[key] = CachedEmbedder(
                OpenRouterEmbedder(client, s.embedding_dimensions),
                shared_cache(s),
                s.embedding_model,
                s.embedding_dimensions,
                s.cache_embedding_ttl_seconds,
            )
        return _embedders[key]

    async def known_model_ids(self) -> set[str] | None:
        """The chat model IDs that OpenRouter lists, or None when the lookup fails."""
        return await self._listed("/models")

    async def embedding_choices(self, current: str) -> list[str]:
        """The embedding models that the page offers: the checked ones that OpenRouter lists now,
        and the current one. When the list is not available, the checked ones."""
        listed = await self._listed("/embeddings/models")
        offered = [m for m in EMBEDDING_CHOICES if listed is None or m in listed]
        return offered if current in offered else [current, *offered]

    async def _listed(self, path: str) -> set[str] | None:
        s = self._settings
        cache = shared_cache(s)
        key = f"model-list:{s.openrouter_base_url}{path}"
        if (cached := await cache.get(key)) is not None:
            return set(json.loads(cached))
        ids = await asyncio.to_thread(self._fetch_ids, path)
        if ids is not None:
            await cache.set(key, json.dumps(sorted(ids)).encode(), s.model_list_ttl_seconds)
        return ids

    def _fetch_ids(self, path: str) -> set[str] | None:
        s = self._settings
        request = urllib.request.Request(  # noqa: S310  # configured https base URL
            f"{s.openrouter_base_url}{path}",
            headers={"Authorization": f"Bearer {s.openrouter_api_key.get_secret_value()}"},
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request, timeout=s.model_list_timeout_seconds
            ) as response:
                ids = {model["id"] for model in json.load(response)["data"]}
        except Exception as exc:  # an unchecked save is better than no save
            logger.warning("model list lookup failed", extra={"error": repr(exc)})
            return None
        return ids


async def close_model_clients() -> None:
    """Closes the HTTP clients of every cached model; called when the process stops."""
    for model in _chat_clients.values():
        await model.aclose()
    _chat_clients.clear()
    _embedders.clear()
