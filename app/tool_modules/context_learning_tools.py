"""
Context Learning Tools - Jarvis' Self-Improvement

Tools for learning context → tool patterns:
- Learn from historical tool usage
- Suggest tools based on query context
- Record tool successes for continuous learning
- View learned mappings
- Detect session types
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def learn_from_tool_history(
    days: int = 30,
    min_occurrences: int = 2,
    **kwargs
) -> Dict[str, Any]:
    """
    Learn context → tool mappings from my historical tool usage.

    Analyzes successful tool calls and extracts keyword → tool patterns.

    Args:
        days: Number of days to analyze (default: 30)
        min_occurrences: Minimum keyword occurrences to save (default: 2)

    Returns:
        Dict with learning results
    """
    try:
        from app.services.context_tool_learner import get_context_tool_learner

        learner = get_context_tool_learner()
        return learner.learn_from_audit(days=days, min_occurrences=min_occurrences)

    except Exception as e:
        logger.error(f"Learn from history failed: {e}")
        return {"success": False, "error": str(e)}


def suggest_tools_for_query(
    query: str,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Get tool suggestions based on query context.

    Uses learned patterns to suggest which tools might be useful.

    Args:
        query: The user's query to analyze
        limit: Max suggestions to return (default: 5)

    Returns:
        Dict with tool suggestions and confidence scores
    """
    try:
        from app.services.context_tool_learner import get_context_tool_learner

        learner = get_context_tool_learner()
        return learner.suggest_tools(query=query, limit=limit)

    except Exception as e:
        logger.error(f"Suggest tools failed: {e}")
        return {"success": False, "error": str(e)}


def record_tool_outcome(
    query: str,
    tool_name: str,
    success: bool = True,
    duration_ms: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record a tool execution outcome for learning.

    Called after each tool execution to update context mappings.

    Args:
        query: The original query that led to this tool
        tool_name: Name of the tool that was executed
        success: Whether the tool call succeeded (default: True)
        duration_ms: How long the tool took (optional)

    Returns:
        Dict with recording result
    """
    try:
        from app.services.context_tool_learner import get_context_tool_learner

        learner = get_context_tool_learner()
        return learner.record_tool_success(
            query=query,
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"Record outcome failed: {e}")
        return {"success": False, "error": str(e)}


def get_learned_mappings(
    limit: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Get my top learned keyword → tool mappings.

    Shows the most reliable patterns I've learned.

    Args:
        limit: Max mappings to return (default: 30)

    Returns:
        Dict with top mappings
    """
    try:
        from app.services.context_tool_learner import get_context_tool_learner

        learner = get_context_tool_learner()
        return learner.get_top_mappings(limit=limit)

    except Exception as e:
        logger.error(f"Get mappings failed: {e}")
        return {"success": False, "error": str(e)}


def get_tool_trigger_contexts(
    tool_name: str,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get contexts/keywords that typically lead to a specific tool.

    Helps understand when a tool is most useful.

    Args:
        tool_name: The tool to analyze
        limit: Max contexts to return (default: 20)

    Returns:
        Dict with triggering contexts for the tool
    """
    try:
        from app.services.context_tool_learner import get_context_tool_learner

        learner = get_context_tool_learner()
        return learner.get_tool_contexts(tool_name=tool_name, limit=limit)

    except Exception as e:
        logger.error(f"Get tool contexts failed: {e}")
        return {"success": False, "error": str(e)}


def detect_current_session_type(
    recent_tools: List[str] = None,
    query: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Detect the current session type based on context.

    Analyzes recent tools and query to determine if this is a
    coding, planning, research, communication, or introspection session.

    Args:
        recent_tools: List of recently used tool names (optional)
        query: Current query to analyze (optional)

    Returns:
        Dict with detected session type and confidence
    """
    try:
        from app.services.context_tool_learner import get_context_tool_learner

        learner = get_context_tool_learner()
        return learner.detect_session_type(
            recent_tools=recent_tools or [],
            query=query
        )

    except Exception as e:
        logger.error(f"Detect session type failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
CONTEXT_LEARNING_TOOLS = [
    {
        "name": "learn_from_tool_history",
        "description": "Learn context → tool mappings from my historical tool usage. Analyzes successful tool calls to build keyword patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30)"
                },
                "min_occurrences": {
                    "type": "integer",
                    "description": "Minimum keyword occurrences to save (default: 2)"
                }
            }
        }
    },
    {
        "name": "suggest_tools_for_query",
        "description": "Get tool suggestions based on query context. Uses learned patterns to suggest which tools might be useful for a given query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to analyze for tool suggestions"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max suggestions to return (default: 5)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "record_tool_outcome",
        "description": "Record a tool execution outcome for learning. Updates context mappings based on success/failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The original query that led to this tool"
                },
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool that was executed"
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether the tool call succeeded (default: true)"
                },
                "duration_ms": {
                    "type": "integer",
                    "description": "How long the tool took in milliseconds"
                }
            },
            "required": ["query", "tool_name"]
        }
    },
    {
        "name": "get_learned_mappings",
        "description": "Get my top learned keyword → tool mappings. Shows the most reliable context patterns I've discovered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max mappings to return (default: 30)"
                }
            }
        }
    },
    {
        "name": "get_tool_trigger_contexts",
        "description": "Get contexts/keywords that typically lead to a specific tool. Helps understand when a tool is most useful.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The tool to analyze"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max contexts to return (default: 20)"
                }
            },
            "required": ["tool_name"]
        }
    },
    {
        "name": "detect_current_session_type",
        "description": "Detect the current session type (coding, planning, research, communication, introspection) based on recent tools and query context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recent_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recently used tool names"
                },
                "query": {
                    "type": "string",
                    "description": "Current query to analyze"
                }
            }
        }
    }
]
