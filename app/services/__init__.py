"""Services package with lazy exports for optional submodules."""

from __future__ import annotations

from typing import Any

__all__ = [
    "init_self_knowledge",
    "store_knowledge",
    "query_knowledge",
    "query_before_response",
    "populate_initial_knowledge",
    "get_tool_knowledge",
]

_SELF_KNOWLEDGE_EXPORTS = {
    "init_self_knowledge": "init_collection",
    "store_knowledge": "store_knowledge",
    "query_knowledge": "query_knowledge",
    "query_before_response": "query_before_response",
    "populate_initial_knowledge": "populate_initial_knowledge",
    "get_tool_knowledge": "get_tool_knowledge",
}


def __getattr__(name: str) -> Any:
    if name not in _SELF_KNOWLEDGE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import self_knowledge

    return getattr(self_knowledge, _SELF_KNOWLEDGE_EXPORTS[name])
