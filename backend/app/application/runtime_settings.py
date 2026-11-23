"""Runtime settings: the saved values over the defaults, and the change that needs a re-ingest."""

from dataclasses import fields, replace

from app.domain.runtime_settings import RuntimeSettings, RuntimeSettingsRepository

# These change the chunks or their vectors, so the stored chunks no longer match after a change.
INDEX_FIELDS = ("chunk_tokens", "overlap_tokens", "embedding_model")


def merge_runtime_settings(defaults: RuntimeSettings, saved: dict[str, object]) -> RuntimeSettings:
    """The saved values over the defaults; keys that are not settings are ignored."""
    known = {f.name for f in fields(defaults)}
    values = {k: v for k, v in saved.items() if k in known}
    return replace(defaults, **values)  # type: ignore[arg-type]  # saved through the validated API


async def load_runtime_settings(
    defaults: RuntimeSettings, repository: RuntimeSettingsRepository
) -> RuntimeSettings:
    return merge_runtime_settings(defaults, await repository.load())


def index_changed(old: RuntimeSettings, new: RuntimeSettings) -> bool:
    return any(getattr(old, name) != getattr(new, name) for name in INDEX_FIELDS)
