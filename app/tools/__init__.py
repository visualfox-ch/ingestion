"""
Jarvis tools package.
"""

import importlib.util
import sys
from pathlib import Path

from .base import ToolCategory, ToolMetadata
from .decision_support_tools import (
    get_decision_support_tools,
    execute_decision_support_tool,
    is_decision_support_tool,
)
from .goal_tools import (
    get_goal_tools,
    execute_goal_tool,
    is_goal_tool,
)
from .kb_analytics_tools import (
    get_kb_analytics_tools,
    execute_kb_analytics_tool,
    is_kb_analytics_tool,
)
from .specialist_tools import (
    get_specialist_tools,
    execute_specialist_tool,
    is_specialist_tool,
)
from .agent_message_tools import (
    get_agent_message_tools,
    execute_agent_message_tool,
    is_agent_message_tool,
)
from .context_tools import (
    get_context_tools,
    execute_context_tool,
    is_context_tool,
)
from .cross_session_tools import (
    get_cross_session_tools,
    execute_cross_session_tool,
    is_cross_session_tool,
)


def _load_legacy_tools_module():
    """Load legacy app/tools.py so existing imports keep working."""
    module_name = "app._tools_legacy"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    legacy_path = Path(__file__).resolve().parent.parent / "tools.py"
    spec = importlib.util.spec_from_file_location(module_name, legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load legacy tools module from {legacy_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_LEGACY_TOOLS = _load_legacy_tools_module()

# Re-export commonly imported symbols from legacy tools.py.
TOOL_DEFINITIONS = _LEGACY_TOOLS.TOOL_DEFINITIONS
TOOL_REGISTRY = _LEGACY_TOOLS.TOOL_REGISTRY
get_tool_definitions = _LEGACY_TOOLS.get_tool_definitions
execute_tool = _LEGACY_TOOLS.execute_tool


def __getattr__(name):
    """Fallback to legacy tools module for broad compatibility."""
    try:
        return getattr(_LEGACY_TOOLS, name)
    except AttributeError as exc:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'") from exc

__all__ = [
    "ToolCategory",
    "ToolMetadata",
    "get_decision_support_tools",
    "execute_decision_support_tool",
    "is_decision_support_tool",
    "get_goal_tools",
    "execute_goal_tool",
    "is_goal_tool",
    "get_kb_analytics_tools",
    "execute_kb_analytics_tool",
    "is_kb_analytics_tool",
    "get_specialist_tools",
    "execute_specialist_tool",
    "is_specialist_tool",
    "get_agent_message_tools",
    "execute_agent_message_tool",
    "is_agent_message_tool",
    "get_context_tools",
    "execute_context_tool",
    "is_context_tool",
    "get_cross_session_tools",
    "execute_cross_session_tool",
    "is_cross_session_tool",
    "TOOL_DEFINITIONS",
    "TOOL_REGISTRY",
    "get_tool_definitions",
    "execute_tool",
]
