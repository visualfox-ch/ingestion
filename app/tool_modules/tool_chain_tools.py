"""
Tool Chain Tools - Phase 2.2

Tools for smart tool chain management:
- Learn chains from historical usage
- Suggest tool sequences
- Get common chains
- Track chain effectiveness
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def learn_tool_chains(
    days: int = 30,
    min_occurrences: int = 2,
    **kwargs
) -> Dict[str, Any]:
    """
    Learn tool chains from historical usage.

    Analyzes tool_audit to find common tool sequences
    (tools used together within a time window).

    Args:
        days: Number of days to analyze (default: 30)
        min_occurrences: Minimum times a chain must occur (default: 2)

    Returns:
        Dict with learning results
    """
    try:
        from app.services.smart_tool_chain_service import get_smart_tool_chain_service

        service = get_smart_tool_chain_service()
        return service.learn_chains_from_audit(days=days, min_occurrences=min_occurrences)

    except Exception as e:
        logger.error(f"Learn tool chains failed: {e}")
        return {"success": False, "error": str(e)}


def suggest_tool_chain(
    trigger_tool: str = None,
    query: str = None,
    limit: int = 3,
    **kwargs
) -> Dict[str, Any]:
    """
    Suggest tool chains based on trigger tool or query.

    Recommends sequences of tools that commonly work together
    for similar tasks.

    Args:
        trigger_tool: Tool that starts the chain (optional)
        query: Query to match against chain keywords (optional)
        limit: Max chains to suggest (default: 3)

    Returns:
        Dict with suggested chains and reasoning
    """
    try:
        from app.services.smart_tool_chain_service import get_smart_tool_chain_service

        service = get_smart_tool_chain_service()
        return service.suggest_chain(
            trigger_tool=trigger_tool,
            query=query,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Suggest tool chain failed: {e}")
        return {"success": False, "error": str(e)}


def get_top_tool_chains(
    limit: int = 10,
    min_length: int = 2,
    **kwargs
) -> Dict[str, Any]:
    """
    Get the most common tool chains.

    Shows frequently used tool sequences with success rates.

    Args:
        limit: Max chains to return (default: 10)
        min_length: Minimum chain length (default: 2)

    Returns:
        Dict with top chains
    """
    try:
        from app.services.smart_tool_chain_service import get_smart_tool_chain_service

        service = get_smart_tool_chain_service()
        return service.get_top_chains(limit=limit, min_length=min_length)

    except Exception as e:
        logger.error(f"Get top tool chains failed: {e}")
        return {"success": False, "error": str(e)}


def get_chains_for_tool(
    tool_name: str,
    position: str = "any",
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Get chains that include a specific tool.

    Find what tool sequences commonly include a given tool.

    Args:
        tool_name: The tool to find chains for
        position: "start" (chains starting with tool),
                  "end" (chains ending with tool),
                  "any" (tool anywhere in chain)
        limit: Max chains to return (default: 5)

    Returns:
        Dict with chains containing the tool
    """
    try:
        from app.services.smart_tool_chain_service import get_smart_tool_chain_service

        service = get_smart_tool_chain_service()
        return service.get_chains_for_tool(
            tool_name=tool_name,
            position=position,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get chains for tool failed: {e}")
        return {"success": False, "error": str(e)}


def record_tool_chain(
    chain: List[str],
    success: bool = True,
    duration_ms: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record a tool chain execution.

    Track when a sequence of tools is used together
    to improve future suggestions.

    Args:
        chain: List of tool names in order
        success: Whether the chain completed successfully
        duration_ms: Total duration in milliseconds (optional)

    Returns:
        Dict with recording result
    """
    try:
        from app.services.smart_tool_chain_service import get_smart_tool_chain_service

        service = get_smart_tool_chain_service()
        return service.record_chain_usage(
            chain=chain,
            success=success,
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"Record tool chain failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
TOOL_CHAIN_TOOLS = [
    {
        "name": "learn_tool_chains",
        "description": "Learn tool chains from historical usage. Analyzes tool sequences to find common patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30)"
                },
                "min_occurrences": {
                    "type": "integer",
                    "description": "Minimum times a chain must occur (default: 2)"
                }
            }
        }
    },
    {
        "name": "suggest_tool_chain",
        "description": "Suggest tool chains based on a trigger tool or query. Recommends sequences of tools that work well together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trigger_tool": {
                    "type": "string",
                    "description": "Tool that starts the chain"
                },
                "query": {
                    "type": "string",
                    "description": "Query to match against chain keywords"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max chains to suggest (default: 3)"
                }
            }
        }
    },
    {
        "name": "get_top_tool_chains",
        "description": "Get the most common tool chains. Shows frequently used tool sequences with success rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max chains to return (default: 10)"
                },
                "min_length": {
                    "type": "integer",
                    "description": "Minimum chain length (default: 2)"
                }
            }
        }
    },
    {
        "name": "get_chains_for_tool",
        "description": "Get chains that include a specific tool. Find what sequences commonly include a given tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The tool to find chains for"
                },
                "position": {
                    "type": "string",
                    "enum": ["start", "end", "any"],
                    "description": "Position of tool in chain: 'start', 'end', or 'any'"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max chains to return (default: 5)"
                }
            },
            "required": ["tool_name"]
        }
    },
    {
        "name": "record_tool_chain",
        "description": "Record a tool chain execution. Track tool sequences for future suggestions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tool names in order"
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether the chain completed successfully"
                },
                "duration_ms": {
                    "type": "integer",
                    "description": "Total duration in milliseconds"
                }
            },
            "required": ["chain"]
        }
    },
    # Tier 2: Tool Chain Intelligence Tools
    {
        "name": "recommend_tool_chains",
        "description": "Get intelligent tool chain recommendations for a query. Suggests tool sequences based on learned patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to get recommendations for"
                },
                "current_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools already used (to avoid duplicates)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max recommendations (default: 3)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_chain_intelligence_stats",
        "description": "Get statistics about tool chain intelligence: learned mappings, clusters, success rates.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "learn_chain_intent_clusters",
        "description": "Learn intent clusters from query-chain mappings. Groups similar queries and identifies their common chains.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_samples": {
                    "type": "integer",
                    "description": "Minimum samples for a cluster (default: 5)"
                }
            }
        }
    }
]


def recommend_tool_chains(
    query: str,
    current_tools: List[str] = None,
    limit: int = 3,
    **kwargs
) -> Dict[str, Any]:
    """Get intelligent tool chain recommendations."""
    try:
        from app.services.tool_chain_intelligence import get_tool_chain_intelligence

        intelligence = get_tool_chain_intelligence()
        recommendations = intelligence.recommend_chains_for_query(
            query=query,
            current_tools=current_tools,
            limit=limit
        )

        return {
            "success": True,
            "query": query[:100],
            "recommendations": [
                {
                    "chain": rec.chain,
                    "confidence": round(rec.confidence, 2),
                    "reason": rec.reason,
                    "success_rate": round(rec.success_rate, 2),
                    "based_on_patterns": rec.based_on_patterns
                }
                for rec in recommendations
            ],
            "count": len(recommendations)
        }

    except Exception as e:
        logger.error(f"Recommend tool chains failed: {e}")
        return {"success": False, "error": str(e)}


def get_chain_intelligence_stats(**kwargs) -> Dict[str, Any]:
    """Get tool chain intelligence statistics."""
    try:
        from app.services.tool_chain_intelligence import get_tool_chain_intelligence

        intelligence = get_tool_chain_intelligence()
        return intelligence.get_intelligence_stats()

    except Exception as e:
        logger.error(f"Get chain intelligence stats failed: {e}")
        return {"success": False, "error": str(e)}


def learn_chain_intent_clusters(
    min_samples: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Learn intent clusters from query-chain mappings."""
    try:
        from app.services.tool_chain_intelligence import get_tool_chain_intelligence

        intelligence = get_tool_chain_intelligence()
        return intelligence.learn_intent_clusters(min_samples=min_samples)

    except Exception as e:
        logger.error(f"Learn chain intent clusters failed: {e}")
        return {"success": False, "error": str(e)}
