import os
import tempfile

# Test values only. app.main reads settings at import time.
TEST_ENV = {
    "OPENROUTER_API_KEY": "test-key",
    "OPENROUTER_BASE_URL": "http://openrouter.test/api/v1",
    "LLM_REWRITE_MODEL": "test/rewrite",
    "LLM_GRADE_MODEL": "test/grade",
    "LLM_GENERATE_MODEL": "test/generate",
    "EMBEDDING_MODEL": "test/embed",
    "EMBEDDING_DIMENSIONS": "8",
    "DATABASE_URL": "postgresql://test:test@db.test:5432/test",
    "STORAGE_BACKEND": "filesystem",
    "STORAGE_FS_ROOT": tempfile.mkdtemp(prefix="storage-"),
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)
