import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_contract_check_runs_without_settings() -> None:
    # CI runs the export with no .env, so it must not load the application settings.
    env = {"PATH": os.environ["PATH"]}
    result = subprocess.run(
        [sys.executable, "-m", "app.api.contract", "--check"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
