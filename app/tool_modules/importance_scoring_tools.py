"""
Importance Scoring Tools - Phase B2 (AGI Evolution)

Tools for Jarvis to score and retrieve memories by importance:
- Score content importance
- Retrieve with composite scoring (recency + importance + similarity)
- Track entity importance
- Manage importance factors

Based on Park et al. (2023) Generative Agents.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def score_content_importance(
    content: str,
    context: Dict = None,
    entities: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Score the importance of content.

    Analyzes text for importance factors like urgency, decisions,
    action items, emotional content, etc.

    Args:
        content: The text to score
        context: Optional context info
        entities: Entities to check for mentions

    Returns:
        Dict with importance scores and detected factors
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.score_importance(
            content=content,
            context=context,
            entities=entities
        )

    except Exception as e:
        logger.error(f"Score content importance failed: {e}")
        return {"success": False, "error": str(e)}


def retrieve_by_relevance(
    query: str,
    limit: int = 10,
    recency_weight: float = 0.3,
    importance_weight: float = 0.4,
    similarity_weight: float = 0.3,
    domain: str = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Retrieve memories using composite relevance scoring.

    Formula: score = recency_w * recency + importance_w * importance + similarity_w * similarity

    Args:
        query: Search query
        limit: Max results (default: 10)
        recency_weight: Weight for recency (default: 0.3)
        importance_weight: Weight for importance (default: 0.4)
        similarity_weight: Weight for similarity (default: 0.3)
        domain: Filter by domain
        session_id: Session ID for logging

    Returns:
        Dict with ranked memories
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.retrieve_relevant(
            query=query,
            limit=limit,
            recency_weight=recency_weight,
            importance_weight=importance_weight,
            similarity_weight=similarity_weight,
            domain=domain,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Retrieve by relevance failed: {e}")
        return {"success": False, "error": str(e)}


def update_entity_importance(
    entity_name: str,
    entity_type: str = "concept",
    is_interaction: bool = False,
    manual_boost: float = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Update importance tracking for an entity.

    Track people, projects, concepts, etc. and their importance.

    Args:
        entity_name: Name of the entity
        entity_type: Type (person, project, concept, location)
        is_interaction: Whether this is a direct interaction
        manual_boost: Manual importance adjustment (-1 to 1)

    Returns:
        Dict with updated importance
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.update_entity_importance(
            entity_name=entity_name,
            entity_type=entity_type,
            interaction=is_interaction,
            manual_boost=manual_boost
        )

    except Exception as e:
        logger.error(f"Update entity importance failed: {e}")
        return {"success": False, "error": str(e)}


def get_important_entities(
    entity_type: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get most important entities.

    Args:
        entity_type: Filter by type (person, project, concept, location)
        limit: Max results (default: 20)

    Returns:
        Dict with important entities
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.get_important_entities(
            entity_type=entity_type,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Get important entities failed: {e}")
        return {"success": False, "error": str(e)}


def add_importance_factor(
    factor_name: str,
    factor_type: str,
    detection_pattern: str,
    base_score: float = 0.5,
    weight: float = 1.0,
    description: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Add a new importance factor.

    Args:
        factor_name: Name of the factor
        factor_type: Type (content, context, entity, emotional)
        detection_pattern: Regex pattern to detect
        base_score: Base importance contribution (0-1)
        weight: Weight when combining (default: 1.0)
        description: Description

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.add_importance_factor(
            factor_name=factor_name,
            factor_type=factor_type,
            detection_pattern=detection_pattern,
            base_score=base_score,
            weight=weight,
            description=description
        )

    except Exception as e:
        logger.error(f"Add importance factor failed: {e}")
        return {"success": False, "error": str(e)}


def get_importance_factors(
    **kwargs
) -> Dict[str, Any]:
    """
    Get all active importance factors.

    Returns:
        Dict with importance factors
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.get_importance_factors()

    except Exception as e:
        logger.error(f"Get importance factors failed: {e}")
        return {"success": False, "error": str(e)}


def decay_memory_recency(
    decay_factor: float = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Apply recency decay to all memories.

    Should be called periodically (e.g., hourly).

    Args:
        decay_factor: Custom decay factor (default: based on config)

    Returns:
        Dict with update count
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.decay_all_recency(decay_factor=decay_factor)

    except Exception as e:
        logger.error(f"Decay memory recency failed: {e}")
        return {"success": False, "error": str(e)}


def get_scoring_stats(
    days: int = 7,
    **kwargs
) -> Dict[str, Any]:
    """
    Get statistics about importance scoring and retrieval.

    Args:
        days: Days to analyze (default: 7)

    Returns:
        Dict with scoring statistics
    """
    try:
        from app.services.importance_scoring_service import get_importance_service

        service = get_importance_service()
        return service.get_scoring_stats(days=days)

    except Exception as e:
        logger.error(f"Get scoring stats failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
IMPORTANCE_SCORING_TOOLS = [
    {
        "name": "score_content_importance",
        "description": "Score the importance of content. Analyzes for urgency, decisions, action items, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The text to score"
                },
                "context": {
                    "type": "object",
                    "description": "Optional context info"
                },
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Entities to check for mentions"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "retrieve_by_relevance",
        "description": "Retrieve memories using composite scoring: recency + importance + similarity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10)"
                },
                "recency_weight": {
                    "type": "number",
                    "description": "Weight for recency (default: 0.3)"
                },
                "importance_weight": {
                    "type": "number",
                    "description": "Weight for importance (default: 0.4)"
                },
                "similarity_weight": {
                    "type": "number",
                    "description": "Weight for similarity (default: 0.3)"
                },
                "domain": {
                    "type": "string",
                    "description": "Filter by domain"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "update_entity_importance",
        "description": "Update importance tracking for an entity (person, project, concept).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Name of the entity"
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "project", "concept", "location"],
                    "description": "Type of entity"
                },
                "is_interaction": {
                    "type": "boolean",
                    "description": "Whether this is a direct interaction"
                },
                "manual_boost": {
                    "type": "number",
                    "description": "Manual importance adjustment (-1 to 1)"
                }
            },
            "required": ["entity_name"]
        }
    },
    {
        "name": "get_important_entities",
        "description": "Get most important entities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "project", "concept", "location"],
                    "description": "Filter by type"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            }
        }
    },
    {
        "name": "add_importance_factor",
        "description": "Add a new importance factor (pattern that affects scoring).",
        "input_schema": {
            "type": "object",
            "properties": {
                "factor_name": {
                    "type": "string",
                    "description": "Name of the factor"
                },
                "factor_type": {
                    "type": "string",
                    "enum": ["content", "context", "entity", "emotional"],
                    "description": "Type of factor"
                },
                "detection_pattern": {
                    "type": "string",
                    "description": "Regex pattern to detect"
                },
                "base_score": {
                    "type": "number",
                    "description": "Base importance contribution (0-1)"
                },
                "weight": {
                    "type": "number",
                    "description": "Weight when combining (default: 1.0)"
                },
                "description": {
                    "type": "string",
                    "description": "Description"
                }
            },
            "required": ["factor_name", "factor_type", "detection_pattern"]
        }
    },
    {
        "name": "get_importance_factors",
        "description": "Get all active importance factors.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "decay_memory_recency",
        "description": "Apply recency decay to all memories. Run periodically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decay_factor": {
                    "type": "number",
                    "description": "Custom decay factor"
                }
            }
        }
    },
    {
        "name": "get_scoring_stats",
        "description": "Get statistics about importance scoring and retrieval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to analyze (default: 7)"
                }
            }
        }
    }
]
