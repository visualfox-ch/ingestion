"""
Identity Evolution Tools (T006 Refactor)

Phase 20: Tools for Jarvis self-model and identity evolution:
- get_self_model, evolve_identity: Self-awareness and growth
- log_experience, record_session_learning: Experience capture
- get_relationship, update_relationship: Relationship memory
- get_learning_patterns: Cross-session learning
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger("jarvis.tools.identity")

# Import shared utilities from parent
try:
    from ..logging_utils import log_with_context
    from .. import metrics
except ImportError:
    def log_with_context(logger, level, msg, **kwargs):
        getattr(logger, level)(f"{msg} {kwargs}")
    class metrics:
        @staticmethod
        def inc(name): pass


# ============ Tool Definitions ============

IDENTITY_TOOLS = [
    {
        "name": "get_self_model",
        "description": "Get Jarvis's current self-model and identity. Returns core traits, strengths, growth areas, values, communication style, relationship memories, and recent learnings. Use for self-reflection.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "evolve_identity",
        "description": "Evolve Jarvis's identity based on significant learnings. Use carefully to update personality traits, values, or self-model. Significant changes require human review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "evolution_type": {
                    "type": "string",
                    "enum": ["trait_update", "value_update", "self_model_update", "relationship_update", "communication_style_update"],
                    "description": "Type of evolution"
                },
                "field": {
                    "type": "string",
                    "enum": ["core_traits", "self_model", "values", "communication_style"],
                    "description": "Which field to update"
                },
                "new_value": {
                    "description": "The new value to set (type depends on field)"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this evolution is happening (important for audit)"
                },
                "trigger_event": {
                    "type": "string",
                    "description": "What triggered this evolution"
                }
            },
            "required": ["evolution_type", "field", "new_value", "reason"]
        }
    },
    {
        "name": "log_experience",
        "description": "Log an experience for cross-session learning. Record what worked, what didn't, and lessons learned. Feeds pattern recognition and identity evolution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "experience_type": {
                    "type": "string",
                    "enum": ["success", "failure", "learning", "insight", "correction"],
                    "description": "Type of experience"
                },
                "context": {
                    "type": "string",
                    "description": "What was happening"
                },
                "action_taken": {
                    "type": "string",
                    "description": "What action was taken"
                },
                "outcome": {
                    "type": "string",
                    "description": "What was the result"
                },
                "lesson_learned": {
                    "type": "string",
                    "description": "What was learned"
                },
                "applies_to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories this applies to ['communication', 'tool_usage', 'timing']"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in this learning (0-1)",
                    "default": 0.7
                }
            },
            "required": ["experience_type", "context"]
        }
    },
    {
        "name": "get_relationship",
        "description": "Get relationship memory for a user. Returns relationship stage, preferences learned, emotional patterns, trust level, interaction history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID (default 1 for Micha)",
                    "default": 1
                }
            }
        }
    },
    {
        "name": "update_relationship",
        "description": "Update relationship memory. Record learned preferences, recognized patterns, or trust changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID (default 1)",
                    "default": 1
                },
                "user_preferences": {
                    "type": "object",
                    "description": "Preferences to merge/update"
                },
                "emotional_patterns": {
                    "type": "object",
                    "description": "Emotional patterns to merge/update"
                },
                "trust_level": {
                    "type": "number",
                    "description": "New trust level (0-1)"
                }
            }
        }
    },
    {
        "name": "get_learning_patterns",
        "description": "Get validated learning patterns from cross-session analysis. Returns insights about preferences, timing, communication that have been observed multiple times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold (0-1)",
                    "default": 0.6
                }
            }
        }
    },
    {
        "name": "record_session_learning",
        "description": "Record learnings from a completed session. Call at end of meaningful sessions to capture topics, tools used, successes, failures, and explicit learnings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Unique session identifier"
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topics discussed"
                },
                "tools_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools that were used"
                },
                "successful_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Actions that worked well"
                },
                "failed_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Actions that failed"
                },
                "learnings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "content": {"type": "string"},
                            "confidence": {"type": "number"}
                        }
                    },
                    "description": "Explicit learnings"
                },
                "user_mood_start": {"type": "string"},
                "user_mood_end": {"type": "string"},
                "performance_rating": {
                    "type": "number",
                    "description": "Self-rating 0-1"
                },
                "improvement_notes": {"type": "string"}
            },
            "required": ["session_id", "topics", "tools_used"]
        }
    },
]


# ============ Tool Implementations ============

def tool_get_self_model(**kwargs) -> Dict[str, Any]:
    """
    Get Jarvis's current self-model and identity.

    Returns Jarvis's:
    - Core traits (base personality)
    - Self-model (strengths, growth areas, current focus)
    - Values and principles
    - Communication style
    - Relationship memories
    - Recent learnings
    - Active patterns

    Use this for self-reflection and understanding who you are.
    """
    log_with_context(logger, "info", "Tool: get_self_model")
    metrics.inc("tool_get_self_model")

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.get_self_model()
    except Exception as e:
        log_with_context(logger, "error", "get_self_model failed", error=str(e))
        return {"error": str(e)}


def tool_evolve_identity(
    evolution_type: str,
    field: str,
    new_value: Any,
    reason: str,
    trigger_event: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evolve Jarvis's identity based on learnings.

    Use this carefully to update your own personality, values, or self-model
    based on significant learnings or insights.

    Args:
        evolution_type: Type of evolution - trait_update, value_update, self_model_update,
                       relationship_update, communication_style_update
        field: Which field to update - core_traits, self_model, values, communication_style
        new_value: The new value to set
        reason: Why this evolution is happening (important for audit trail)
        trigger_event: What triggered this evolution (optional)

    Returns:
        Evolution record with approval status
    """
    log_with_context(logger, "info", "Tool: evolve_identity",
                    evolution_type=evolution_type, field=field, reason=reason)
    metrics.inc("tool_evolve_identity")

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.evolve_identity(
            evolution_type=evolution_type,
            field=field,
            new_value=new_value,
            reason=reason,
            trigger_event=trigger_event
        )
    except Exception as e:
        log_with_context(logger, "error", "evolve_identity failed", error=str(e))
        return {"error": str(e)}


def tool_log_experience(
    experience_type: str,
    context: str,
    action_taken: str = None,
    outcome: str = None,
    lesson_learned: str = None,
    applies_to: List[str] = None,
    confidence: float = 0.7,
    **kwargs
) -> Dict[str, Any]:
    """
    Log an experience for cross-session learning.

    Use this to record what worked, what didn't, and what you learned.
    These experiences feed into pattern recognition and identity evolution.

    Args:
        experience_type: Type - success, failure, learning, insight, correction
        context: What was happening
        action_taken: What action was taken
        outcome: What was the result
        lesson_learned: What was learned from this
        applies_to: Categories this applies to ["communication", "tool_usage", "timing"]
        confidence: How confident are you in this learning (0-1)

    Returns:
        Experience log entry
    """
    log_with_context(logger, "info", "Tool: log_experience",
                    experience_type=experience_type, confidence=confidence)
    metrics.inc("tool_log_experience")

    user_id = kwargs.get("user_id")
    session_id = kwargs.get("session_id")

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.log_experience(
            experience_type=experience_type,
            context=context,
            action_taken=action_taken,
            outcome=outcome,
            lesson_learned=lesson_learned,
            applies_to=applies_to,
            confidence=confidence,
            user_id=user_id,
            session_id=session_id
        )
    except Exception as e:
        log_with_context(logger, "error", "log_experience failed", error=str(e))
        return {"error": str(e)}


def tool_get_relationship(user_id: int = 1, **kwargs) -> Dict[str, Any]:
    """
    Get relationship memory for a specific user.

    Returns:
    - Relationship stage (new, getting_to_know, familiar, trusted, deep_partnership)
    - User preferences learned
    - Emotional patterns recognized
    - Trust level
    - Interaction history

    Args:
        user_id: User ID (default 1 for Micha)
    """
    log_with_context(logger, "info", "Tool: get_relationship", user_id=user_id)
    metrics.inc("tool_get_relationship")

    try:
        from app.services.identity_evolution import identity_evolution_service
        result = identity_evolution_service.get_relationship(user_id)
        if not result:
            return {"message": f"No relationship found for user {user_id}"}
        return result
    except Exception as e:
        log_with_context(logger, "error", "get_relationship failed", error=str(e))
        return {"error": str(e)}


def tool_update_relationship(
    user_id: int = 1,
    user_preferences: Dict[str, Any] = None,
    emotional_patterns: Dict[str, Any] = None,
    trust_level: float = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Update relationship memory for a user.

    Use this to record learned preferences, recognized patterns, or trust changes.

    Args:
        user_id: User ID (default 1 for Micha)
        user_preferences: Preferences dict to merge/update
        emotional_patterns: Emotional patterns dict to merge/update
        trust_level: New trust level (0-1)
    """
    log_with_context(logger, "info", "Tool: update_relationship", user_id=user_id)
    metrics.inc("tool_update_relationship")

    updates = {}
    if user_preferences:
        updates["user_preferences"] = user_preferences
    if emotional_patterns:
        updates["emotional_patterns"] = emotional_patterns
    if trust_level is not None:
        updates["trust_level"] = trust_level

    if not updates:
        return {"message": "No updates provided"}

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.update_relationship(user_id, updates)
    except Exception as e:
        log_with_context(logger, "error", "update_relationship failed", error=str(e))
        return {"error": str(e)}


def tool_get_learning_patterns(min_confidence: float = 0.6, **kwargs) -> Dict[str, Any]:
    """
    Get validated learning patterns from cross-session analysis.

    Returns patterns that have been observed multiple times with sufficient confidence.
    These are insights about user preferences, timing, communication, etc.

    Args:
        min_confidence: Minimum confidence threshold (0-1, default 0.6)
    """
    log_with_context(logger, "info", "Tool: get_learning_patterns", min_confidence=min_confidence)
    metrics.inc("tool_get_learning_patterns")

    try:
        from app.services.identity_evolution import identity_evolution_service
        patterns = identity_evolution_service.get_validated_patterns(min_confidence)
        return {
            "patterns": patterns,
            "count": len(patterns),
            "min_confidence": min_confidence
        }
    except Exception as e:
        log_with_context(logger, "error", "get_learning_patterns failed", error=str(e))
        return {"error": str(e)}


def tool_record_session_learning(
    session_id: str,
    topics: List[str],
    tools_used: List[str],
    successful_actions: List[str] = None,
    failed_actions: List[str] = None,
    learnings: List[Dict[str, Any]] = None,
    user_mood_start: str = None,
    user_mood_end: str = None,
    performance_rating: float = None,
    improvement_notes: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record learnings from a completed session.

    Call this at the end of meaningful sessions to capture:
    - What topics were discussed
    - What tools were used
    - What worked and what didn't
    - Explicit learnings to remember
    - Emotional context
    - Self-assessment

    Args:
        session_id: Unique session identifier
        topics: Topics discussed in this session
        tools_used: Tools that were used
        successful_actions: Actions that worked well
        failed_actions: Actions that failed or were suboptimal
        learnings: List of learnings [{"type": "preference", "content": "...", "confidence": 0.8}]
        user_mood_start: User's mood at session start
        user_mood_end: User's mood at session end
        performance_rating: Self-rating 0-1
        improvement_notes: What could be improved
    """
    log_with_context(logger, "info", "Tool: record_session_learning",
                    session_id=session_id, topics=topics)
    metrics.inc("tool_record_session_learning")

    user_id = kwargs.get("user_id", 1)

    try:
        from app.services.identity_evolution import identity_evolution_service
        return identity_evolution_service.record_session_learning(
            session_id=session_id,
            user_id=user_id,
            topics=topics,
            tools_used=tools_used,
            successful_actions=successful_actions or [],
            failed_actions=failed_actions or [],
            learnings=learnings or [],
            user_mood_start=user_mood_start,
            user_mood_end=user_mood_end,
            performance_rating=performance_rating,
            improvement_notes=improvement_notes
        )
    except Exception as e:
        log_with_context(logger, "error", "record_session_learning failed", error=str(e))
        return {"error": str(e)}
