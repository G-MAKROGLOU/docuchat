"""Only graph.py may import LangGraph; the other chat modules see injected ports only."""

import ast
from pathlib import Path

import app.application.chat as chat_package

CHAT_DIR = Path(chat_package.__file__).parent


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_only_graph_module_imports_langgraph() -> None:
    offenders = [
        path.name
        for path in sorted(CHAT_DIR.rglob("*.py"))
        if path != CHAT_DIR / "graph.py"
        and any(
            m == "langgraph" or m.startswith("langgraph.")
            for m in imported_modules(path.read_text(encoding="utf-8"))
        )
    ]

    assert offenders == []
