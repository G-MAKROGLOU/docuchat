"""A streaming-only LangChain chat model for OpenRouter that reads the SSE stream with httpx and
json. The OpenAI SDK builds pydantic objects for every chunk, which was half of the API CPU of a
chat turn. LangChain still sends its callbacks, so traces keep the model name and the usage."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LangSmithParams
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr, SecretStr

_ROLES = {"human": "user", "ai": "assistant", "system": "system"}
# Worth one more try before any text arrived; other errors are final.
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


FIRST_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 10.0


class ModelStreamError(RuntimeError):
    pass


def _retry_after(response: httpx.Response) -> float:
    """The wait that a 429 or 5xx asks for, else one second; never more than ten."""
    try:
        wait = float(response.headers.get("retry-after", FIRST_BACKOFF_SECONDS))
    except ValueError:
        wait = FIRST_BACKOFF_SECONDS
    return min(max(wait, 0.0), MAX_BACKOFF_SECONDS)


def usage_metadata(usage: dict[str, Any]) -> UsageMetadata:
    result = UsageMetadata(
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
    )
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cached is not None:
        result["input_token_details"] = {"cache_read": int(cached)}
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if reasoning is not None:
        result["output_token_details"] = {"reasoning": int(reasoning)}
    return result


DONE = "[DONE]"


def _data(line: str) -> str | None:
    """The data of one SSE line. None for comments and blank lines."""
    return line[5:].strip() if line.startswith("data:") else None


class OpenRouterStreamChat(BaseChatModel):
    model: str
    base_url: str
    api_key: SecretStr
    max_tokens: int
    reasoning_effort: str
    timeout: float = 60.0
    max_retries: int = 1
    # Tests pass a mock transport and a sleep that records; production uses the defaults.
    transport: httpx.AsyncBaseTransport | None = None
    sleep: Callable[[float], Awaitable[None]] = Field(default=asyncio.sleep, exclude=True)

    _client: httpx.AsyncClient | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "openrouter-stream"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        # Same parameter names as the ChatOpenAI generations in the traces.
        return {
            "model_name": self.model,
            "temperature": 0,
            "max_completion_tokens": self.max_tokens,
        }

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> LangSmithParams:
        return LangSmithParams(
            ls_provider="openrouter",
            ls_model_name=self.model,
            ls_model_type="chat",
            ls_temperature=0,
            ls_max_tokens=self.max_tokens,
        )

    def _http(self) -> httpx.AsyncClient:
        # One client per model, so connections are reused between turns.
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _body(self, messages: Sequence[BaseMessage]) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": _ROLES[m.type], "content": m.text} for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "reasoning": {"effort": self.reasoning_effort},
        }

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        body = self._body(messages)
        headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
        started = False
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                async with self._http().stream(
                    "POST", "/chat/completions", json=body, headers=headers
                ) as response:
                    if response.status_code != httpx.codes.OK:
                        text = (await response.aread()).decode(errors="replace")[:300]
                        if response.status_code in _RETRY_STATUSES and not last:
                            await self.sleep(_retry_after(response))
                            continue
                        raise ModelStreamError(f"model call failed: {response.status_code} {text}")
                    async for line in response.aiter_lines():
                        data = _data(line)
                        if data == DONE:
                            return
                        if data:
                            for chunk in self._chunks(json.loads(data)):
                                started = True
                                yield chunk
                    # A closed connection without [DONE] would pass a cut answer as complete.
                    raise ModelStreamError("model stream ended early")
            except httpx.TransportError as exc:
                # A second try after text was sent would repeat that text.
                if started or last:
                    raise ModelStreamError(f"model call failed: {type(exc).__name__}") from exc
                await self.sleep(FIRST_BACKOFF_SECONDS)

    @staticmethod
    def _chunks(event: dict[str, Any]) -> Iterator[ChatGenerationChunk]:
        if "error" in event:
            error = event["error"]
            message = error.get("message") if isinstance(error, dict) else error
            raise ModelStreamError(f"model stream failed: {message}")
        choices = event.get("choices") or [{}]
        text = (choices[0].get("delta") or {}).get("content") or ""
        if text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
        if event.get("usage"):
            usage = usage_metadata(event["usage"])
            # OpenRouter reports the cost in USD next to the tokens; the metrics read it.
            cost = {"cost": event["usage"]["cost"]} if "cost" in event["usage"] else {}
            message = AIMessageChunk(content="", usage_metadata=usage, response_metadata=cost)
            yield ChatGenerationChunk(message=message)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("This model only streams; use astream.")
