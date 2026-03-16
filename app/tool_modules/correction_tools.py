"""
Correction Learning Tools

Tools for learning from and applying user corrections.
"""

from typing import Dict, Any, List, Optional

from ..services.correction_learner import get_correction_learner

# Tool definitions
CORRECTION_TOOLS = [
    {
        "name": "detect_correction",
        "description": "Detect if a user message is a correction. Use this when a user seems to be correcting your previous response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_message": {
                    "type": "string",
                    "description": "The user's message to check"
                },
                "previous_response": {
                    "type": "string",
                    "description": "Your previous response that might be getting corrected"
                }
            },
            "required": ["user_message"]
        }
    },
    {
        "name": "process_correction",
        "description": "Process a detected correction - extract pattern and store for learning. Call this when you detect that a user is correcting you.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_message": {
                    "type": "string",
                    "description": "The correction message from user"
                },
                "previous_response": {
                    "type": "string",
                    "description": "Your response that was corrected"
                },
                "session_id": {
                    "type": "string",
                    "description": "Current session ID"
                }
            },
            "required": ["user_message", "previous_response"]
        }
    },
    {
        "name": "check_corrections",
        "description": "Check if there are any learned corrections relevant to a query. Use before responding to avoid repeating past mistakes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to check against learned corrections"
                },
                "error_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: filter by error types (name, preference, factual, tone, general)"
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold (0-1, default 0.5)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "store_correction",
        "description": "Manually store a correction pattern. Use when you learn something that should be remembered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "error_type": {
                    "type": "string",
                    "enum": ["name", "preference", "factual", "tone", "tool_choice", "general"],
                    "description": "Category of the correction"
                },
                "error_pattern": {
                    "type": "string",
                    "description": "The pattern/phrase that was wrong"
                },
                "correct_response": {
                    "type": "string",
                    "description": "What the correct response should be"
                },
                "correction_text": {
                    "type": "string",
                    "description": "What the user said as correction"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in this correction (0-1)"
                }
            },
            "required": ["error_type", "error_pattern", "correct_response"]
        }
    },
    {
        "name": "get_correction_stats",
        "description": "Get statistics about learned corrections.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default 30)"
                }
            }
        }
    }
]


def detect_correction(
    user_message: str,
    previous_response: str = None
) -> Dict[str, Any]:
    """Detect if a user message is a correction."""
    learner = get_correction_learner()
    return learner.detect_correction(user_message, previous_response)


def process_correction(
    user_message: str,
    previous_response: str,
    session_id: str = None
) -> Dict[str, Any]:
    """Process a correction - extract and store pattern."""
    learner = get_correction_learner()
    return learner.process_correction(
        user_message=user_message,
        previous_response=previous_response,
        session_id=session_id
    )


def check_corrections(
    query: str,
    error_types: List[str] = None,
    min_confidence: float = 0.5
) -> Dict[str, Any]:
    """Check for relevant corrections."""
    learner = get_correction_learner()
    corrections = learner.get_relevant_corrections(
        query=query,
        error_types=error_types,
        min_confidence=min_confidence
    )
    return {
        "found": len(corrections) > 0,
        "count": len(corrections),
        "corrections": corrections
    }


def store_correction(
    error_type: str,
    error_pattern: str,
    correct_response: str,
    correction_text: str = None,
    confidence: float = 0.7
) -> Dict[str, Any]:
    """Manually store a correction pattern."""
    learner = get_correction_learner()
    return learner.store_correction(
        error_type=error_type,
        error_pattern=error_pattern,
        correction_text=correction_text or f"Korrektur: {correct_response}",
        correct_response=correct_response,
        confidence=confidence
    )


def get_correction_stats(days: int = 30) -> Dict[str, Any]:
    """Get correction statistics."""
    learner = get_correction_learner()
    return learner.get_correction_stats(days=days)
