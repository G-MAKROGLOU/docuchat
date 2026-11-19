"""Application settings. Values come from the environment only."""

from functools import lru_cache

from pydantic import SecretStr, ValidationError
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
    llm_rewrite_model: str
    llm_grade_model: str
    llm_generate_model: str
    embedding_model: str
    embedding_dimensions: int
    database_url: SecretStr

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None


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
