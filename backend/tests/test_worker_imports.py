import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).parents[1]
FORBIDDEN = ("langgraph", "fastapi", "app.application.chat")
# A fresh interpreter: the test process has loaded the API already.
PROBE = (
    "import importlib, json, sys; "
    "importlib.import_module(sys.argv[1]); "
    "print(json.dumps(list(sys.modules)))"
)


def forbidden(name: str) -> bool:
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN)


@pytest.mark.parametrize("module", ["app.worker.__main__", "app.worker.corpus_init"])
def test_a_worker_entry_point_loads_no_chat_or_http_code(module: str) -> None:
    result = subprocess.run(  # noqa: S603  # fixed arguments, no shell
        [sys.executable, "-c", PROBE, module],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )

    assert [name for name in json.loads(result.stdout) if forbidden(name)] == []
