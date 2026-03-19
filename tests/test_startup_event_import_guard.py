"""Regression guard for startup_event import-shadowing bugs.

This test prevents local imports inside startup_event that would shadow
module-level imports (e.g. os/json/time) and can cause UnboundLocalError.
"""

from __future__ import annotations

import ast
from pathlib import Path


MAIN_FILE = Path(__file__).resolve().parents[1] / "app" / "main.py"
DISALLOWED_INNER_IMPORTS = {"os", "json", "time"}


def _get_startup_event_function(tree: ast.AST) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "startup_event":
            return node
    raise AssertionError("startup_event function not found in app/main.py")


def test_startup_event_has_no_shadowing_imports() -> None:
    """startup_event must not contain local imports for shared stdlib modules."""
    source = MAIN_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    startup_event = _get_startup_event_function(tree)

    found_shadowing = set()

    for node in ast.walk(startup_event):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_name = alias.asname or alias.name.split(".")[0]
                if imported_name in DISALLOWED_INNER_IMPORTS:
                    found_shadowing.add(imported_name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_module = node.module.split(".")[0]
                if imported_module in DISALLOWED_INNER_IMPORTS:
                    found_shadowing.add(imported_module)

    assert not found_shadowing, (
        "startup_event contains local imports that can shadow module-level names: "
        f"{sorted(found_shadowing)}"
    )
