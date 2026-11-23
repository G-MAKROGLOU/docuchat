import os
import sys
import tempfile
from collections.abc import Iterator

import pytest

# Test values only, set unconditionally so a developer .env cannot leak into tests.
# app.main reads settings at import time.
TEST_ENV = {
    "OPENROUTER_API_KEY": "test-key",
    "OPENROUTER_BASE_URL": "http://openrouter.test/api/v1",
    "LLM_CHAT_MODEL": "test/chat",
    "LLM_REWRITE_MODEL": "test/rewrite",
    "LLM_GRADE_MODEL": "test/grade",
    "LLM_GENERATE_MODEL": "test/generate",
    "EMBEDDING_MODEL": "test/embed",
    "EMBEDDING_DIMENSIONS": "8",
    "DATABASE_URL": "postgresql://test:test@db.test:5432/test",
    "CACHE_URL": "redis://cache.test:6379/0",
    "STORAGE_BACKEND": "filesystem",
    "STORAGE_FS_ROOT": tempfile.mkdtemp(prefix="storage-"),
}
for key, value in TEST_ENV.items():
    os.environ[key] = value
# Keys from a developer .env must not start a real Langfuse client in tests.
for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
    os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    yield
    # Only when a test loaded the app: importing app.main here would change the import order.
    main = sys.modules.get("app.main")
    if main is not None:
        main.app.dependency_overrides.clear()
