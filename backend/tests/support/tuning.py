"""The tuning objects for tests, built from the documented values in .env.example."""

from datetime import timedelta

from app.config import get_settings
from app.wiring import (
    chat_limits,
    detector_thresholds,
    heartbeat_limit,
    ingest_limits,
    search_limits,
)

SETTINGS = get_settings()
CHAT = chat_limits(SETTINGS)
SEARCH = search_limits(SETTINGS)
THRESHOLDS = detector_thresholds(SETTINGS)
INGEST = ingest_limits(SETTINGS)
HEARTBEAT = heartbeat_limit(SETTINGS)
TICK = timedelta(seconds=SETTINGS.worker_tick_seconds)
CHUNK_BYTES = SETTINGS.storage_stream_chunk_bytes
