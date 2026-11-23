"""Application settings. Values come from the environment only."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingSettingsError(RuntimeError):
    pass


class Settings(BaseSettings):
    # Empty values count as absent, so a blank required variable fails at startup.
    model_config = SettingsConfigDict(
        env_file=None, env_ignore_empty=True, extra="ignore", frozen=True
    )

    openrouter_api_key: SecretStr
    openrouter_base_url: str
    # Cheap model for conversation turns; the three below run the document pipeline.
    llm_chat_model: str
    llm_rewrite_model: str
    llm_grade_model: str
    llm_generate_model: str
    embedding_model: str
    embedding_dimensions: int
    # Switch for the ablation: the drug and section prefix on each embedded chunk.
    embedding_prefix: bool = True
    # Switch for the ablation: no grading, the plain rule check only, or the rule then the model.
    grader_mode: Literal["off", "rule", "llm"] = "llm"
    database_url: SecretStr
    # The shared cache (Redis), for all API processes and the worker.
    cache_url: SecretStr

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    storage_backend: Literal["s3", "filesystem"]
    # No endpoint URL means real AWS S3.
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str | None = None
    storage_fs_root: str | None = None
    storage_stream_chunk_bytes: int

    # Database pool, per process.
    db_pool_min_size: int
    db_pool_max_size: int
    db_statement_timeout_ms: int
    db_pool_timeout_seconds: float
    db_pool_max_waiting: int
    db_probe_timeout_seconds: float

    # Shared cache.
    cache_timeout_seconds: float
    cache_embedding_ttl_seconds: int
    cache_chat_ttl_seconds: int

    # Model clients.
    model_timeout_seconds: float
    chat_model_max_retries: int
    embedding_max_retries: int
    embedding_batch_size: int
    model_list_ttl_seconds: int
    model_list_timeout_seconds: float
    stream_first_backoff_seconds: float
    stream_max_backoff_seconds: float
    max_output_tokens_chat: int
    max_output_tokens_rewrite: int
    max_output_tokens_grade: int
    max_output_tokens_generate: int

    # Chat turn.
    chat_history_turns: int
    chat_max_query_chars: int
    chat_grade_retries: int
    chat_turn_deadline_seconds: float
    chat_max_reply_chars: int
    chat_intake_list_max: int
    chat_max_suggestions: int
    chat_max_suggestion_chars: int

    # Search and context selection.
    search_rrf_k: int
    search_max_chunks: int
    search_token_budget: int
    search_min_per_drug: int
    search_leg_timeout_seconds: float
    search_title_boost: float
    search_phrase_boost: float

    # Defaults of the runtime settings, until the user saves others.
    default_chunk_tokens: int
    default_overlap_tokens: int
    default_top_k: int

    # Drug detection.
    detector_min_key_length: int
    detector_min_tail_length: int
    detector_fuzzy_threshold: float
    detector_candidate_floor: float
    detector_ambiguity_margin: float
    detector_max_choices: int
    detector_rebuild_seconds: float

    # Ingestion of one label.
    chunk_anchor_words: int
    ingest_max_page_misses: float
    locator_window: int
    locator_min_piece: int
    locator_slack: int
    locator_max_span: int
    pdf_row_tolerance: float
    failure_reason_max_chars: int

    # Ingest worker and its passes.
    worker_tick_seconds: float
    worker_heartbeat_limit_seconds: float
    ingest_schedule_hours: float
    ingest_concurrency: int
    label_queue_batch: int
    update_check_concurrency: int
    runtime_refresh_seconds: float

    # Label source (DailyMed).
    source_delay_seconds: float
    source_max_bytes: int
    source_attempts: int
    source_first_backoff_seconds: float
    source_timeout_seconds: float
    catalog_timeout_seconds: float
    label_search_limit: int
    label_fetch_limit: int

    # API.
    thumbnail_width: int
    thumbnail_concurrency: int
    thumbnail_ttl_seconds: int
    thumbnail_max_age_seconds: int
    readiness_check_timeout_seconds: float
    pool_metrics_interval_seconds: float

    @model_validator(mode="after")
    def _storage_settings_complete(self) -> Self:
        required = (
            {"s3_bucket": self.s3_bucket, "s3_region": self.s3_region}
            if self.storage_backend == "s3"
            else {"storage_fs_root": self.storage_fs_root}
        )
        missing = [name.upper() for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"STORAGE_BACKEND={self.storage_backend} needs {', '.join(missing)}")
        return self


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}" for err in exc.errors()
        ]
        raise MissingSettingsError(
            "Invalid or missing environment variables:\n  " + "\n  ".join(problems)
        ) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
