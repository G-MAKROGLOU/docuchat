"""The one factory for model and embedding clients (OpenRouter through LangChain)."""

import json
import logging
import urllib.request
from collections.abc import Sequence

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.config import Settings
from app.domain.ports import Embedder

logger = logging.getLogger(__name__)

EMBEDDING_BATCH = 100


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
        return self._checked([await self._client.aembed_query(text)])[0]


class ModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def embedder(self) -> Embedder:
        s = self._settings
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
        return OpenRouterEmbedder(client, s.embedding_dimensions)

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
