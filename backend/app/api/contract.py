"""Stream event schema route and contract export. Usage: python -m app.api.contract [--check]"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from app.api.schemas.stream import STREAM_EVENT_ADAPTER

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contract"
STREAM_SCHEMA_PATH = "/schemas/stream-events.json"

router = APIRouter(tags=["contract"])


def stream_events_schema() -> dict[str, Any]:
    schema = STREAM_EVENT_ADAPTER.json_schema(mode="serialization")
    return {"title": "StreamEvent", **schema}


@router.get(STREAM_SCHEMA_PATH)
async def get_stream_events_schema() -> dict[str, Any]:
    return stream_events_schema()


def _render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def contract_files(app: FastAPI) -> dict[Path, str]:
    return {
        CONTRACT_DIR / "openapi.json": _render(app.openapi()),
        CONTRACT_DIR / "stream-events.schema.json": _render(stream_events_schema()),
    }


def main(argv: list[str] | None = None) -> int:
    from app.api.factory import create_api  # noqa: PLC0415  # factory imports this module

    parser = argparse.ArgumentParser(description="Write or check the files in contract/.")
    parser.add_argument("--check", action="store_true", help="fail if a file is out of date")
    args = parser.parse_args(argv)

    stale = []
    for path, content in contract_files(create_api()).items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"wrote contract/{path.name}")
    if stale:
        print(f"Out of date: {', '.join(stale)}. Run: python -m app.api.contract", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
