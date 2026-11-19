import pytest

from app.config import MissingSettingsError, load_settings
from tests.conftest import TEST_ENV


def test_missing_variables_fail_with_their_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("DATABASE_URL", "")

    with pytest.raises(MissingSettingsError) as exc_info:
        load_settings()

    message = str(exc_info.value)
    assert "OPENROUTER_API_KEY: Field required" in message
    assert "DATABASE_URL: Field required" in message
    assert "LLM_REWRITE_MODEL" not in message


def test_complete_environment_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)

    settings = load_settings()

    assert settings.embedding_dimensions == 8
    assert settings.langfuse_host is None
