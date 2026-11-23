"""Prometheus metrics. With PROMETHEUS_MULTIPROC_DIR set (several API processes), each process
writes its values to files in that folder and the /metrics endpoint adds them up."""

import asyncio
import os
import time
from typing import Any, Protocol, get_args
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
    start_http_server,
)

from app.domain.ingestion_state import IngestionPhase

_FAST = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_SLOW = (0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0, 64.0, 120.0)

HTTP_REQUESTS = Counter(
    "docuchat_http_requests_total",
    "HTTP requests by route and status.",
    ["method", "route", "status"],
)
HTTP_SECONDS = Histogram(
    "docuchat_http_request_seconds",
    "HTTP request time until the response ends (whole stream for chat).",
    ["method", "route"],
    buckets=(*_FAST, 10.0, 20.0, 30.0, 60.0, 120.0),
)
CHAT_TURNS = Counter("docuchat_chat_turns_total", "Chat turns by outcome.", ["outcome"])
CHAT_TURN_SECONDS = Histogram(
    "docuchat_chat_turn_seconds", "Chat turn time to the last event.", ["outcome"], buckets=_SLOW
)
CHAT_FIRST_TOKEN_SECONDS = Histogram(
    "docuchat_chat_first_token_seconds", "Chat turn time to the first answer text.", buckets=_SLOW
)
LLM_CALLS = Counter(
    "docuchat_llm_calls_total", "Model calls by role and result.", ["role", "status"]
)
LLM_SECONDS = Histogram(
    "docuchat_llm_call_seconds", "Model call time by role.", ["role"], buckets=_SLOW
)
LLM_TOKENS = Counter(
    "docuchat_llm_tokens_total", "Model tokens by role and kind.", ["role", "kind"]
)
LLM_COST = Counter("docuchat_llm_cost_usd_total", "Model cost that OpenRouter reported.", ["role"])
SEARCH_SECONDS = Histogram(
    "docuchat_search_seconds", "Search step time by kind.", ["kind"], buckets=_FAST
)
DB_POOL = Gauge(
    "docuchat_db_pool_connections",
    "Database pool connections by state, over the live API processes.",
    ["state"],
    multiprocess_mode="livesum",
)
CACHE_REQUESTS = Counter(
    "docuchat_cache_requests_total", "Shared cache reads and writes by kind and result.",
    ["kind", "result"],
)  # fmt: skip
INGESTED_DOCUMENTS = Counter(
    "docuchat_ingested_documents_total", "Documents handled by ingestion passes.", ["result"]
)
INGEST_DOCUMENT_SECONDS = Histogram(
    "docuchat_ingest_document_seconds", "Time to ingest one document.", buckets=_SLOW
)
INGESTION_PHASE = Gauge("docuchat_ingestion_phase", "1 for the worker's current phase.", ["phase"])
WORKER_REPORT_TIME = Gauge(
    "docuchat_ingest_worker_report_timestamp_seconds", "Unix time of the worker's last report."
)


def _multiprocess() -> bool:
    return bool(os.environ.get("PROMETHEUS_MULTIPROC_DIR"))


def render() -> tuple[bytes, str]:
    """The metrics text of every live process, or of this process alone."""
    if _multiprocess():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def process_stopped() -> None:
    """Drops this process from the live gauges."""
    if _multiprocess():
        multiprocess.mark_process_dead(os.getpid())  # type: ignore[no-untyped-call]


_PHASES: tuple[str, ...] = get_args(IngestionPhase)


def serve(port: int) -> None:
    """A metrics HTTP server in a thread, for the ingest worker, which has no web app."""
    start_http_server(port)


def observe_ingest(result: Any, seconds: float) -> None:
    outcome = "failed" if result.error else "skipped" if result.skipped else "ingested"
    INGESTED_DOCUMENTS.labels(outcome).inc()
    if outcome == "ingested":
        INGEST_DOCUMENT_SECONDS.observe(seconds)


def observe_phase(phase: str) -> None:
    for name in _PHASES:
        INGESTION_PHASE.labels(name).set(1 if name == phase else 0)
    WORKER_REPORT_TIME.set_to_current_time()


class PoolStats(Protocol):
    def get_stats(self) -> dict[str, int]: ...


async def watch_pool(pool: PoolStats, every: float) -> None:
    """Copies the pool counters into the gauge every few seconds until cancelled."""
    while True:
        stats = pool.get_stats()
        DB_POOL.labels("open").set(stats.get("pool_size", 0))
        DB_POOL.labels("idle").set(stats.get("pool_available", 0))
        DB_POOL.labels("waiting").set(stats.get("requests_waiting", 0))
        await asyncio.sleep(every)


def _role(name: str | None) -> str:
    # The models are named "llm-<role>" in the factory.
    return (name or "unknown").removeprefix("llm-")


def _cost(response: LLMResult) -> float | None:
    usage = (response.llm_output or {}).get("token_usage") or {}
    if isinstance(usage.get("cost"), int | float):
        return float(usage["cost"])
    for generations in response.generations:
        for generation in generations:
            metadata = getattr(getattr(generation, "message", None), "response_metadata", {})
            if isinstance(metadata.get("cost"), int | float):
                return float(metadata["cost"])
    return None


class LlmMetrics(AsyncCallbackHandler):
    """Counts model calls, their time, tokens and cost. Shared by every model client."""

    def __init__(self) -> None:
        self._started: dict[UUID, tuple[str, float]] = {}

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any
    ) -> None:
        # LangChain passes the model's name ("llm-<role>") in serialized, a run name in kwargs.
        name = kwargs.get("name") or serialized.get("name")
        self._started[run_id] = (_role(name), time.perf_counter())

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        role, started = self._started.pop(run_id, ("unknown", time.perf_counter()))
        LLM_CALLS.labels(role, "ok").inc()
        LLM_SECONDS.labels(role).observe(time.perf_counter() - started)
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if usage:
                    LLM_TOKENS.labels(role, "input").inc(usage.get("input_tokens", 0))
                    LLM_TOKENS.labels(role, "output").inc(usage.get("output_tokens", 0))
        cost = _cost(response)
        if cost is not None:
            LLM_COST.labels(role).inc(cost)

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        role, started = self._started.pop(run_id, ("unknown", time.perf_counter()))
        LLM_CALLS.labels(role, "error").inc()
        LLM_SECONDS.labels(role).observe(time.perf_counter() - started)


LLM_METRICS = LlmMetrics()
