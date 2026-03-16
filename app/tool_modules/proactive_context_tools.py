"""
Proactive Context Tools - Phase 2.1

Tools for proactive context loading:
- Analyze queries for context needs
- Load relevant context automatically
- Track context effectiveness
- Get context loading statistics
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def analyze_context_needs(
    query: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze a query to determine what context might be needed.

    Identifies context types (preferences, recent conversations, project, etc.)
    that could be useful for answering the query.

    Args:
        query: The query to analyze

    Returns:
        Dict with needed context types and priorities
    """
    try:
        from app.services.proactive_context_service import get_proactive_context_service

        service = get_proactive_context_service()
        return service.analyze_query(query)

    except Exception as e:
        logger.error(f"Analyze context needs failed: {e}")
        return {"success": False, "error": str(e)}


def load_proactive_context(
    query: str,
    user_id: str = "default",
    session_type: str = None,
    max_items: int = 3,
    **kwargs
) -> Dict[str, Any]:
    """
    Proactively load relevant context for a query.

    Analyzes the query and loads:
    - User preferences
    - Recent conversations
    - Project context
    - Calendar/communication context
    - Session-based context

    Args:
        query: The query to load context for
        user_id: User identifier (default: "default")
        session_type: Current session type (optional)
        max_items: Max items per context type (default: 3)

    Returns:
        Dict with loaded context organized by type
    """
    try:
        from app.services.proactive_context_service import get_proactive_context_service

        service = get_proactive_context_service()
        return service.load_proactive_context(
            query=query,
            user_id=user_id,
            session_type=session_type,
            max_items_per_type=max_items
        )

    except Exception as e:
        logger.error(f"Load proactive context failed: {e}")
        return {"success": False, "error": str(e)}


def mark_context_useful(
    query: str,
    useful_types: List[str],
    **kwargs
) -> Dict[str, Any]:
    """
    Mark which context types were actually useful.

    Called after a query is processed to provide feedback
    on which context was helpful. Improves future loading.

    Args:
        query: The original query
        useful_types: List of context types that were useful
            (e.g., ["preferences", "recent_conversations"])

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.proactive_context_service import get_proactive_context_service

        service = get_proactive_context_service()
        return service.mark_context_useful(query=query, useful_types=useful_types)

    except Exception as e:
        logger.error(f"Mark context useful failed: {e}")
        return {"success": False, "error": str(e)}


def get_context_effectiveness(
    **kwargs
) -> Dict[str, Any]:
    """
    Get statistics on context loading effectiveness.

    Shows which context types are most useful and how often
    they are loaded vs actually helpful.

    Returns:
        Dict with effectiveness stats per context type
    """
    try:
        from app.services.proactive_context_service import get_proactive_context_service

        service = get_proactive_context_service()
        return service.get_context_stats()

    except Exception as e:
        logger.error(f"Get context effectiveness failed: {e}")
        return {"success": False, "error": str(e)}


def build_context_prompt(
    query: str,
    user_id: str = "default",
    session_type: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Build a context prompt section for a query.

    Loads relevant context and formats it as a prompt section
    that can be injected into the system prompt.

    Args:
        query: The query to build context for
        user_id: User identifier (default: "default")
        session_type: Current session type (optional)

    Returns:
        Dict with formatted context prompt string
    """
    try:
        from app.services.proactive_context_service import get_proactive_context_service

        service = get_proactive_context_service()
        loaded = service.load_proactive_context(
            query=query,
            user_id=user_id,
            session_type=session_type
        )

        prompt = service.build_context_prompt(loaded)

        return {
            "success": True,
            "context_prompt": prompt,
            "types_loaded": list(loaded.get('context', {}).keys())
        }

    except Exception as e:
        logger.error(f"Build context prompt failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
PROACTIVE_CONTEXT_TOOLS = [
    {
        "name": "analyze_context_needs",
        "description": "Analyze a query to determine what context might be needed. Identifies relevant context types like preferences, recent conversations, project context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to analyze"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "load_proactive_context",
        "description": "Proactively load relevant context for a query. Loads user preferences, recent conversations, project context, and session context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to load context for"
                },
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                },
                "session_type": {
                    "type": "string",
                    "description": "Current session type (coding/research/planning/etc.)"
                },
                "max_items": {
                    "type": "integer",
                    "description": "Max items per context type (default: 3)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "mark_context_useful",
        "description": "Mark which context types were actually useful for a query. Provides feedback to improve future context loading.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The original query"
                },
                "useful_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of useful context types (e.g., ['preferences', 'recent_conversations'])"
                }
            },
            "required": ["query", "useful_types"]
        }
    },
    {
        "name": "get_context_effectiveness",
        "description": "Get statistics on context loading effectiveness. Shows which context types are most useful.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "build_context_prompt",
        "description": "Build a formatted context prompt section for a query. Returns a string ready to inject into system prompt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to build context for"
                },
                "user_id": {
                    "type": "string",
                    "description": "User identifier (default: 'default')"
                },
                "session_type": {
                    "type": "string",
                    "description": "Current session type"
                }
            },
            "required": ["query"]
        }
    }
]
