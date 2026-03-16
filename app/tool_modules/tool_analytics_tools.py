"""
Tool Analytics Tools - Jarvis' Self-Understanding

Provides tools for Jarvis to understand his own tool usage:
- Usage statistics (what tools, how often, success rates)
- Time patterns (when tools work best)
- Context mapping (what queries → what tools)
- Tool chains (common workflows)
- Failure analysis (what to improve)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_my_tool_usage(
    days: int = 30,
    tool_name: Optional[str] = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get my own tool usage statistics.

    Args:
        days: Number of days to analyze (default: 30)
        tool_name: Specific tool to analyze (optional)
        limit: Max tools to return (default: 20)

    Returns:
        Dict with usage stats per tool
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.get_tool_stats(days=days, tool_name=tool_name, limit=limit)

    except Exception as e:
        logger.error(f"Get tool usage failed: {e}")
        return {"success": False, "error": str(e)}


def get_my_time_patterns(
    tool_name: Optional[str] = None,
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze my time-based usage patterns.

    Returns when I'm most active and when tools work best.

    Args:
        tool_name: Specific tool to analyze (optional)
        days: Number of days to analyze (default: 30)

    Returns:
        Dict with hourly/daily patterns and insights
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.get_time_patterns(tool_name=tool_name, days=days)

    except Exception as e:
        logger.error(f"Get time patterns failed: {e}")
        return {"success": False, "error": str(e)}


def get_context_tool_patterns(
    min_occurrences: int = 3,
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze which query patterns lead to which tools.

    Helps me understand context → tool mapping.

    Args:
        min_occurrences: Minimum occurrences to include (default: 3)
        days: Number of days to analyze (default: 30)

    Returns:
        Dict with keyword → tool mappings
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.get_context_tool_mapping(
            min_occurrences=min_occurrences,
            days=days
        )

    except Exception as e:
        logger.error(f"Get context patterns failed: {e}")
        return {"success": False, "error": str(e)}


def get_my_tool_chains(
    days: int = 7,
    min_chain_length: int = 2,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze my tool usage chains within sessions.

    Shows common tool sequences and their success rates.

    Args:
        days: Number of days to analyze (default: 7)
        min_chain_length: Minimum tools in chain (default: 2)

    Returns:
        Dict with common chains and success rates
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.get_tool_chains(days=days, min_chain_length=min_chain_length)

    except Exception as e:
        logger.error(f"Get tool chains failed: {e}")
        return {"success": False, "error": str(e)}


def get_my_failure_analysis(
    days: int = 30,
    limit: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze my tool failures for improvement opportunities.

    Shows which tools fail most and why.

    Args:
        days: Number of days to analyze (default: 30)
        limit: Max tools to return (default: 10)

    Returns:
        Dict with failure analysis and error patterns
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.get_failure_analysis(days=days, limit=limit)

    except Exception as e:
        logger.error(f"Get failure analysis failed: {e}")
        return {"success": False, "error": str(e)}


def get_tool_recommendations(**kwargs) -> Dict[str, Any]:
    """
    Get recommendations for improving my tool usage.

    Analyzes patterns and suggests:
    - Tools to optimize (high failure rate)
    - Usage pattern improvements
    - Underutilized capabilities

    Returns:
        Dict with prioritized recommendations
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.get_recommendations()

    except Exception as e:
        logger.error(f"Get recommendations failed: {e}")
        return {"success": False, "error": str(e)}


def refresh_tool_stats(**kwargs) -> Dict[str, Any]:
    """
    Refresh aggregated tool statistics.

    Updates the jarvis_tool_performance_stats table with current data.

    Returns:
        Dict with aggregation result
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()
        return analytics.aggregate_stats()

    except Exception as e:
        logger.error(f"Refresh stats failed: {e}")
        return {"success": False, "error": str(e)}


def get_tool_usage_summary(**kwargs) -> Dict[str, Any]:
    """
    Get a comprehensive summary of my tool usage.

    Combines multiple analytics for a complete picture:
    - Top tools used
    - Time patterns
    - Recent chains
    - Improvement opportunities

    Returns:
        Dict with comprehensive summary
    """
    try:
        from app.services.tool_usage_analytics import get_tool_usage_analytics

        analytics = get_tool_usage_analytics()

        # Gather all analytics
        stats = analytics.get_tool_stats(days=7, limit=10)
        time_patterns = analytics.get_time_patterns(days=7)
        chains = analytics.get_tool_chains(days=7)
        failures = analytics.get_failure_analysis(days=7, limit=5)
        recommendations = analytics.get_recommendations()

        return {
            "success": True,
            "period": "last_7_days",
            "summary": {
                "total_tool_calls": stats.get("total_calls", 0),
                "unique_tools_used": stats.get("unique_tools_used", 0),
                "top_tools": [t["tool_name"] for t in stats.get("tools", [])[:5]],
                "peak_hour": time_patterns.get("peak_hour"),
                "peak_day": time_patterns.get("peak_day"),
                "common_chains": [c["chain"] for c in chains.get("common_chains", [])[:3]],
                "tools_needing_attention": [
                    f["tool_name"] for f in failures.get("failures", [])
                    if f.get("failure_rate", 0) > 10
                ],
                "insights": time_patterns.get("insights", [])
            },
            "recommendations_count": len(recommendations.get("recommendations", []))
        }

    except Exception as e:
        logger.error(f"Get usage summary failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
TOOL_ANALYTICS_TOOLS = [
    {
        "name": "get_my_tool_usage",
        "description": "Get my own tool usage statistics. Shows which tools I use most, success rates, and performance metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30)"
                },
                "tool_name": {
                    "type": "string",
                    "description": "Specific tool to analyze (optional, analyzes all if not specified)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tools to return (default: 20)"
                }
            }
        }
    },
    {
        "name": "get_my_time_patterns",
        "description": "Analyze my time-based usage patterns. Shows when I'm most active and when tools work best (by hour, by day).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Specific tool to analyze (optional)"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30)"
                }
            }
        }
    },
    {
        "name": "get_context_tool_patterns",
        "description": "Analyze which query patterns lead to which tools. Helps understand context → tool mapping for better tool selection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_occurrences": {
                    "type": "integer",
                    "description": "Minimum occurrences to include (default: 3)"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30)"
                }
            }
        }
    },
    {
        "name": "get_my_tool_chains",
        "description": "Analyze my tool usage chains within sessions. Shows common tool sequences and their success rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)"
                },
                "min_chain_length": {
                    "type": "integer",
                    "description": "Minimum tools in chain (default: 2)"
                }
            }
        }
    },
    {
        "name": "get_my_failure_analysis",
        "description": "Analyze my tool failures for improvement opportunities. Shows which tools fail most and error patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tools to return (default: 10)"
                }
            }
        }
    },
    {
        "name": "get_tool_recommendations",
        "description": "Get recommendations for improving my tool usage. Identifies tools to optimize and usage pattern improvements.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "refresh_tool_stats",
        "description": "Refresh aggregated tool statistics. Updates the performance stats table with current data.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_tool_usage_summary",
        "description": "Get a comprehensive summary of my tool usage. Combines stats, patterns, chains, and recommendations into one overview.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
