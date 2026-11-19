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
    llm_rewrite_model: str
    llm_grade_model: str
    llm_generate_model: str
    embedding_model: str
    embedding_dimensions: int
    database_url: SecretStr

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
