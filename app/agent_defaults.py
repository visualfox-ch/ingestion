"""Shared defaults for the Jarvis agent entrypoints."""

from typing import Optional


DEFAULT_AGENT_MODEL = "claude-sonnet-4-6"


def resolve_agent_model(model: Optional[str]) -> str:
    """Return the canonical default model when no explicit model is provided."""
    return model or DEFAULT_AGENT_MODEL
