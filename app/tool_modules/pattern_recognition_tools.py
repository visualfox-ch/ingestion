"""
Pattern Recognition Tools - Phase 3.3

Tools for statistical pattern recognition:
- Analyze temporal patterns
- Find tool co-occurrence patterns
- Cluster similar queries
- Detect anomalies
- Predict next actions
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def analyze_temporal_patterns(
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze time-based usage patterns.

    Finds patterns like peak hours, active days, etc.

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        Dict with hourly/daily distributions and patterns
    """
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service

        service = get_pattern_recognition_service()
        return service.analyze_temporal_patterns(days=days)

    except Exception as e:
        logger.error(f"Analyze temporal patterns failed: {e}")
        return {"success": False, "error": str(e)}


def analyze_tool_cooccurrence(
    days: int = 30,
    window_minutes: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze which tools are commonly used together.

    Finds co-occurrence patterns within a time window.

    Args:
        days: Number of days to analyze (default: 30)
        window_minutes: Time window for co-occurrence (default: 10)

    Returns:
        Dict with tool pairs and their correlation strength
    """
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service

        service = get_pattern_recognition_service()
        return service.analyze_tool_cooccurrence(
            days=days,
            window_minutes=window_minutes
        )

    except Exception as e:
        logger.error(f"Analyze tool cooccurrence failed: {e}")
        return {"success": False, "error": str(e)}


def cluster_queries(
    days: int = 30,
    min_cluster_size: int = 3,
    **kwargs
) -> Dict[str, Any]:
    """
    Cluster similar queries based on keywords and outcomes.

    Groups queries with similar patterns for prediction.

    Args:
        days: Number of days to analyze (default: 30)
        min_cluster_size: Minimum queries per cluster (default: 3)

    Returns:
        Dict with query clusters and their characteristics
    """
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service

        service = get_pattern_recognition_service()
        return service.cluster_queries(
            days=days,
            min_cluster_size=min_cluster_size
        )

    except Exception as e:
        logger.error(f"Cluster queries failed: {e}")
        return {"success": False, "error": str(e)}


def detect_usage_anomalies(
    days: int = 7,
    **kwargs
) -> Dict[str, Any]:
    """
    Detect anomalies in recent usage patterns.

    Identifies unusual patterns like high failure rates or activity spikes.

    Args:
        days: Number of days to check (default: 7)

    Returns:
        Dict with detected anomalies and their severity
    """
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service

        service = get_pattern_recognition_service()
        return service.detect_anomalies(days=days)

    except Exception as e:
        logger.error(f"Detect usage anomalies failed: {e}")
        return {"success": False, "error": str(e)}


def predict_next_tool(
    recent_tools: List[str],
    context: Dict[str, Any] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Predict the next likely tool based on patterns.

    Uses sequential and co-occurrence patterns.

    Args:
        recent_tools: List of recently used tools
        context: Current context (optional)

    Returns:
        Dict with predicted tool and confidence
    """
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service

        service = get_pattern_recognition_service()
        return service.predict_next_tool(
            recent_tools=recent_tools,
            context=context
        )

    except Exception as e:
        logger.error(f"Predict next tool failed: {e}")
        return {"success": False, "error": str(e)}


def get_recognized_patterns(
    pattern_type: str = None,
    min_confidence: float = 0.3,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get recognized patterns from analysis.

    Shows patterns discovered by the recognition system.

    Args:
        pattern_type: Filter by type (temporal, sequential, categorical, etc.)
        min_confidence: Minimum confidence threshold (default: 0.3)
        limit: Max patterns to return (default: 20)

    Returns:
        Dict with recognized patterns
    """
    try:
        from app.services.pattern_recognition_service import get_pattern_recognition_service

        service = get_pattern_recognition_service()
        return service.get_recognized_patterns(
            pattern_type=pattern_type,
            min_confidence=min_confidence,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get recognized patterns failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
PATTERN_RECOGNITION_TOOLS = [
    {
        "name": "analyze_temporal_patterns",
        "description": "Analyze time-based usage patterns. Finds peak hours, active days, and time preferences.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 30)"
                }
            }
        }
    },
    {
        "name": "analyze_tool_cooccurrence",
        "description": "Analyze which tools are commonly used together within a time window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 30)"
                },
                "window_minutes": {
                    "type": "integer",
                    "description": "Time window for co-occurrence (default: 10)"
                }
            }
        }
    },
    {
        "name": "cluster_queries",
        "description": "Cluster similar queries based on keywords and outcomes for better prediction.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 30)"
                },
                "min_cluster_size": {
                    "type": "integer",
                    "description": "Minimum queries per cluster (default: 3)"
                }
            }
        }
    },
    {
        "name": "detect_usage_anomalies",
        "description": "Detect anomalies like high failure rates or unusual activity spikes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to check (default: 7)"
                }
            }
        }
    },
    {
        "name": "predict_next_tool",
        "description": "Predict the next likely tool based on sequential patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recent_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recently used tools"
                },
                "context": {
                    "type": "object",
                    "description": "Current context"
                }
            },
            "required": ["recent_tools"]
        }
    },
    {
        "name": "get_recognized_patterns",
        "description": "Get recognized patterns from analysis. Shows discovered patterns with confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern_type": {
                    "type": "string",
                    "enum": ["temporal", "sequential", "categorical", "behavioral", "contextual"],
                    "description": "Filter by pattern type"
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence (default: 0.3)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max patterns (default: 20)"
                }
            }
        }
    }
]
