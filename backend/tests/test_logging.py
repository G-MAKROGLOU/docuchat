import json
import logging

from app.infrastructure.logging import JsonFormatter


def test_extras_cannot_overwrite_core_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "t", "levelno": logging.INFO, "levelname": "INFO", "msg": "hello"}
    )
    record.level = "DEBUG"
    record.path = "/health"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["path"] == "/health"
