"""
Uncertainty Quantification Tools - Phase A2 (AGI Evolution)

Tools for Jarvis to assess and express uncertainty:
- Assess confidence in responses
- Track knowledge gaps
- Monitor calibration
- Express appropriate uncertainty
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def assess_my_confidence(
    query: str,
    response: str,
    tool_calls: List[Dict] = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Assess confidence in a response.

    Analyzes the response for uncertainty signals and produces
    calibrated confidence scores.

    Args:
        query: The original query
        response: The response to assess
        tool_calls: Tools that were used
        session_id: Session identifier

    Returns:
        Dict with confidence scores and uncertainty analysis
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.assess_confidence(
            query=query,
            response=response,
            tool_calls=tool_calls,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Assess my confidence failed: {e}")
        return {"success": False, "error": str(e)}


def get_my_knowledge_gaps(
    domain: str = None,
    min_severity: str = None,
    include_resolved: bool = False,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get tracked knowledge gaps.

    Shows what topics I don't know well.

    Args:
        domain: Filter by domain
        min_severity: Minimum severity (low, medium, high, critical)
        include_resolved: Include resolved gaps
        limit: Max gaps to return

    Returns:
        Dict with knowledge gaps
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.get_knowledge_gaps(
            domain=domain,
            min_severity=min_severity,
            include_resolved=include_resolved,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get my knowledge gaps failed: {e}")
        return {"success": False, "error": str(e)}


def resolve_knowledge_gap(
    topic: str,
    domain: str = None,
    resolution_method: str = "learned",
    **kwargs
) -> Dict[str, Any]:
    """
    Mark a knowledge gap as resolved.

    Args:
        topic: The topic that was a gap
        domain: The domain (optional)
        resolution_method: How it was resolved (learned, external_source, acknowledged_limitation)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.resolve_knowledge_gap(
            topic=topic,
            domain=domain,
            resolution_method=resolution_method
        )

    except Exception as e:
        logger.error(f"Resolve knowledge gap failed: {e}")
        return {"success": False, "error": str(e)}


def update_confidence_calibration(
    assessment_id: int,
    was_correct: bool,
    **kwargs
) -> Dict[str, Any]:
    """
    Update calibration based on whether a prediction was correct.

    Helps improve confidence accuracy over time.

    Args:
        assessment_id: ID of the confidence assessment
        was_correct: Whether the prediction turned out to be correct

    Returns:
        Dict with calibration update
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.update_calibration(
            assessment_id=assessment_id,
            was_correct=was_correct
        )

    except Exception as e:
        logger.error(f"Update confidence calibration failed: {e}")
        return {"success": False, "error": str(e)}


def get_calibration_stats(
    days: int = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    Get confidence calibration statistics.

    Shows how well-calibrated my confidence predictions are.

    Args:
        days: Days to analyze (default: 30)

    Returns:
        Dict with calibration metrics by confidence bucket
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.get_calibration_stats(days=days)

    except Exception as e:
        logger.error(f"Get calibration stats failed: {e}")
        return {"success": False, "error": str(e)}


def get_confidence_summary(
    days: int = 7,
    **kwargs
) -> Dict[str, Any]:
    """
    Get summary of confidence assessments.

    Shows confidence distribution over time.

    Args:
        days: Days to analyze (default: 7)

    Returns:
        Dict with confidence summary
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.get_confidence_summary(days=days)

    except Exception as e:
        logger.error(f"Get confidence summary failed: {e}")
        return {"success": False, "error": str(e)}


def add_uncertainty_signal(
    signal_name: str,
    signal_type: str,
    detection_pattern: str,
    confidence_impact: float = -0.1,
    severity: str = "medium",
    **kwargs
) -> Dict[str, Any]:
    """
    Add a new uncertainty signal pattern.

    Args:
        signal_name: Name of the signal
        signal_type: Type (linguistic, knowledge, reasoning, temporal)
        detection_pattern: Regex pattern to detect
        confidence_impact: Impact on confidence (negative reduces)
        severity: Severity level (low, medium, high, critical)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.add_uncertainty_signal(
            signal_name=signal_name,
            signal_type=signal_type,
            detection_pattern=detection_pattern,
            confidence_impact=confidence_impact,
            severity=severity
        )

    except Exception as e:
        logger.error(f"Add uncertainty signal failed: {e}")
        return {"success": False, "error": str(e)}


def get_uncertainty_signals(
    **kwargs
) -> Dict[str, Any]:
    """
    Get all configured uncertainty signals.

    Shows what patterns reduce confidence.

    Returns:
        Dict with uncertainty signals
    """
    try:
        from app.services.uncertainty_service import get_uncertainty_service

        service = get_uncertainty_service()
        return service.get_uncertainty_signals_list()

    except Exception as e:
        logger.error(f"Get uncertainty signals failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
UNCERTAINTY_TOOLS = [
    {
        "name": "assess_my_confidence",
        "description": "Assess confidence in a response. Analyzes for uncertainty signals and produces calibrated scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The original query"
                },
                "response": {
                    "type": "string",
                    "description": "The response to assess"
                },
                "tool_calls": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Tools that were used"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session identifier"
                }
            },
            "required": ["query", "response"]
        }
    },
    {
        "name": "get_my_knowledge_gaps",
        "description": "Get tracked knowledge gaps - topics I don't know well.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter by domain"
                },
                "min_severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Minimum severity"
                },
                "include_resolved": {
                    "type": "boolean",
                    "description": "Include resolved gaps"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max gaps to return (default: 20)"
                }
            }
        }
    },
    {
        "name": "resolve_knowledge_gap",
        "description": "Mark a knowledge gap as resolved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic that was a gap"
                },
                "domain": {
                    "type": "string",
                    "description": "The domain (optional)"
                },
                "resolution_method": {
                    "type": "string",
                    "enum": ["learned", "external_source", "acknowledged_limitation"],
                    "description": "How it was resolved"
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "update_confidence_calibration",
        "description": "Update calibration based on whether a prediction was correct.",
        "input_schema": {
            "type": "object",
            "properties": {
                "assessment_id": {
                    "type": "integer",
                    "description": "ID of the confidence assessment"
                },
                "was_correct": {
                    "type": "boolean",
                    "description": "Whether the prediction was correct"
                }
            },
            "required": ["assessment_id", "was_correct"]
        }
    },
    {
        "name": "get_calibration_stats",
        "description": "Get confidence calibration statistics. Shows how well-calibrated my predictions are.",
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
        "name": "get_confidence_summary",
        "description": "Get summary of confidence assessments over time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 7)"
                }
            }
        }
    },
    {
        "name": "add_uncertainty_signal",
        "description": "Add a new uncertainty signal pattern that affects confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "signal_name": {
                    "type": "string",
                    "description": "Name of the signal"
                },
                "signal_type": {
                    "type": "string",
                    "enum": ["linguistic", "knowledge", "reasoning", "temporal"],
                    "description": "Type of signal"
                },
                "detection_pattern": {
                    "type": "string",
                    "description": "Regex pattern to detect"
                },
                "confidence_impact": {
                    "type": "number",
                    "description": "Impact on confidence (negative reduces)"
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Severity level"
                }
            },
            "required": ["signal_name", "signal_type", "detection_pattern"]
        }
    },
    {
        "name": "get_uncertainty_signals",
        "description": "Get all configured uncertainty signals - patterns that reduce confidence.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
