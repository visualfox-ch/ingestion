"""
Contextual Routing Tools - Phase 3.1

Tools for intelligent tool routing based on context:
- Create routing rules
- Get routing recommendations
- Track routing effectiveness
- Manage tool affinities
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def create_routing_rule(
    rule_name: str,
    context_conditions: Dict[str, Any],
    target_tools: List[str],
    fallback_tool: str = None,
    priority: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a routing rule for conditional tool selection.

    Defines when to route to specific tools based on context.

    Args:
        rule_name: Unique name for the rule
        context_conditions: Conditions that trigger this rule
            - keywords: List of keywords in query
            - session_type: Required session type
            - after_tool: Tool that must have been used recently
            - time_range: [start_hour, end_hour] range
        target_tools: List of tools to route to (priority order)
        fallback_tool: Tool to use if primary tools fail
        priority: Rule priority (higher = checked first)

    Returns:
        Dict with rule creation result
    """
    try:
        from app.services.contextual_tool_router import get_contextual_tool_router

        service = get_contextual_tool_router()
        return service.create_routing_rule(
            rule_name=rule_name,
            context_conditions=context_conditions,
            target_tools=target_tools,
            fallback_tool=fallback_tool,
            priority=priority
        )

    except Exception as e:
        logger.error(f"Create routing rule failed: {e}")
        return {"success": False, "error": str(e)}


def route_tool_selection(
    query: str,
    context: Dict[str, Any] = None,
    available_tools: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get routing recommendation for a query.

    Analyzes query and context to recommend the best tool.

    Args:
        query: The user query
        context: Current context (session_type, recent_tools, etc.)
        available_tools: List of available tools to choose from

    Returns:
        Dict with recommended tool and alternatives
    """
    try:
        from app.services.contextual_tool_router import get_contextual_tool_router

        service = get_contextual_tool_router()
        return service.route_tool(
            query=query,
            context=context,
            available_tools=available_tools
        )

    except Exception as e:
        logger.error(f"Route tool selection failed: {e}")
        return {"success": False, "error": str(e)}


def record_routing_outcome(
    query: str,
    tool_selected: str,
    was_successful: bool,
    context: Dict[str, Any] = None,
    rule_applied: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record the outcome of a tool routing decision.

    Updates affinity scores based on success/failure.

    Args:
        query: The original query
        tool_selected: The tool that was selected
        was_successful: Whether the tool execution was successful
        context: Context at time of routing
        rule_applied: Name of routing rule if one was applied

    Returns:
        Dict with recording confirmation
    """
    try:
        from app.services.contextual_tool_router import get_contextual_tool_router

        service = get_contextual_tool_router()
        return service.record_routing_outcome(
            query=query,
            tool_selected=tool_selected,
            was_successful=was_successful,
            context=context,
            rule_applied=rule_applied
        )

    except Exception as e:
        logger.error(f"Record routing outcome failed: {e}")
        return {"success": False, "error": str(e)}


def get_routing_rules(
    active_only: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Get all routing rules.

    Lists configured rules with their conditions and stats.

    Args:
        active_only: Only return active rules (default: True)

    Returns:
        Dict with list of routing rules
    """
    try:
        from app.services.contextual_tool_router import get_contextual_tool_router

        service = get_contextual_tool_router()
        return service.get_routing_rules(active_only=active_only)

    except Exception as e:
        logger.error(f"Get routing rules failed: {e}")
        return {"success": False, "error": str(e)}


def get_tool_affinities(
    tool_name: str = None,
    context_key: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get learned tool-context affinities.

    Shows which tools work best with which contexts.

    Args:
        tool_name: Get affinities for specific tool
        context_key: Get affinities for specific context
        limit: Max results to return (default: 20)

    Returns:
        Dict with affinity scores
    """
    try:
        from app.services.contextual_tool_router import get_contextual_tool_router

        service = get_contextual_tool_router()
        return service.get_tool_affinities(
            tool_name=tool_name,
            context_key=context_key,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get tool affinities failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
CONTEXTUAL_ROUTING_TOOLS = [
    {
        "name": "create_routing_rule",
        "description": "Create a routing rule for conditional tool selection. Defines when to route to specific tools based on context conditions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_name": {
                    "type": "string",
                    "description": "Unique name for the rule"
                },
                "context_conditions": {
                    "type": "object",
                    "description": "Conditions: keywords (list), session_type (str), after_tool (str), time_range ([start, end])"
                },
                "target_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools to route to (priority order)"
                },
                "fallback_tool": {
                    "type": "string",
                    "description": "Fallback tool if primary tools fail"
                },
                "priority": {
                    "type": "integer",
                    "description": "Rule priority (higher = checked first, default: 50)"
                }
            },
            "required": ["rule_name", "context_conditions", "target_tools"]
        }
    },
    {
        "name": "route_tool_selection",
        "description": "Get routing recommendation for a query. Analyzes query and context to recommend the best tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user query"
                },
                "context": {
                    "type": "object",
                    "description": "Current context (session_type, recent_tools, etc.)"
                },
                "available_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of available tools to choose from"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "record_routing_outcome",
        "description": "Record the outcome of a tool routing decision. Updates affinity scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The original query"
                },
                "tool_selected": {
                    "type": "string",
                    "description": "The tool that was selected"
                },
                "was_successful": {
                    "type": "boolean",
                    "description": "Whether the tool execution was successful"
                },
                "context": {
                    "type": "object",
                    "description": "Context at time of routing"
                },
                "rule_applied": {
                    "type": "string",
                    "description": "Name of routing rule if applied"
                }
            },
            "required": ["query", "tool_selected", "was_successful"]
        }
    },
    {
        "name": "get_routing_rules",
        "description": "Get all routing rules with their conditions and effectiveness stats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "Only return active rules (default: true)"
                }
            }
        }
    },
    {
        "name": "get_tool_affinities",
        "description": "Get learned tool-context affinities. Shows which tools work best with which contexts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Get affinities for specific tool"
                },
                "context_key": {
                    "type": "string",
                    "description": "Get affinities for specific context"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            }
        }
    }
]
