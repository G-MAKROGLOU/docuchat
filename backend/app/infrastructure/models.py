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

EMBEDDING_BATCH = 100
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
_LIST_TTL_SECONDS = 600
# Model clients of this process, shared across settings changes (see ModelFactory).
_chat_clients: dict[tuple[object, ...], "OpenRouterChatModel"] = {}
_embedders: dict[tuple[object, ...], CachedEmbedder] = {}
# Output limits per role, in tokens. The low reasoning effort counts toward them too.
MAX_OUTPUT_TOKENS = {
    ModelRole.CHAT: 1024,
    ModelRole.REWRITE: 1024,
    ModelRole.GRADE: 2048,
    ModelRole.GENERATE: 8192,
}


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
        # the search are reused.
        models[ModelRole.REWRITE] = CachedChatModel(
            models[ModelRole.REWRITE],
            shared_cache(s.cache_url.get_secret_value()),
            f"{ModelRole.REWRITE.value}:{s.llm_rewrite_model}:{self._reasoning_effort}",
        )
        return RoleModels(models)

    def _chat_model(self, role: ModelRole, name: str) -> OpenRouterChatModel:
        """One client pair per role and model in this process: a settings change builds clients
        only for the roles it changes, so the HTTP connections stay in use."""
        s = self._settings
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
                    max_tokens=MAX_OUTPUT_TOKENS[role],
                    # One retry per call, then the turn fails with an error event.
                    max_retries=1,
                    timeout=60,
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
                    max_tokens=MAX_OUTPUT_TOKENS[role],
                    reasoning_effort=self._reasoning_effort,
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
                chunk_size=EMBEDDING_BATCH,
                max_retries=3,
                request_timeout=60,
            )
            _embedders[key] = CachedEmbedder(
                OpenRouterEmbedder(client, s.embedding_dimensions),
                shared_cache(cache_url),
                s.embedding_model,
                s.embedding_dimensions,
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
        cache = shared_cache(s.cache_url.get_secret_value())
        key = f"model-list:{s.openrouter_base_url}{path}"
        if (cached := await cache.get(key)) is not None:
            return set(json.loads(cached))
        ids = await asyncio.to_thread(self._fetch_ids, path)
        if ids is not None:
            await cache.set(key, json.dumps(sorted(ids)).encode(), _LIST_TTL_SECONDS)
        return ids

    def _fetch_ids(self, path: str) -> set[str] | None:
        s = self._settings
        request = urllib.request.Request(  # noqa: S310  # configured https base URL
            f"{s.openrouter_base_url}{path}",
            headers={"Authorization": f"Bearer {s.openrouter_api_key.get_secret_value()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
                ids = {model["id"] for model in json.load(response)["data"]}
        except Exception as exc:  # an unchecked save is better than no save
            logger.warning("model list lookup failed", extra={"error": repr(exc)})
            return None
        return ids

    def embedding_price_per_token(self) -> float | None:
        """USD per input token from OpenRouter, or None when the lookup fails."""
        s = self._settings
        request = urllib.request.Request(  # noqa: S310  # configured https base URL
            f"{s.openrouter_base_url}/embeddings/models",
            headers={"Authorization": f"Bearer {s.openrouter_api_key.get_secret_value()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
                models = json.load(response)["data"]
            model = next(m for m in models if m["id"] == s.embedding_model)
            return float(model["pricing"]["prompt"])
        except Exception as exc:  # the price is for the report only
            logger.warning("embedding price lookup failed", extra={"error": repr(exc)})
            return None


async def close_model_clients() -> None:
    """Closes the HTTP clients of every cached model; called when the process stops."""
    for model in _chat_clients.values():
        await model.aclose()
    _chat_clients.clear()
    _embedders.clear()
