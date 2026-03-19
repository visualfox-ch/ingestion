"""
Tool Suggestion Tools - Phase 21 Option 2B

Tools for getting and managing tool suggestions.
"""
from typing import Dict, Any, List, Optional

from ..observability import get_logger

logger = get_logger("jarvis.tools.suggestions")


def get_tool_suggestions(
    query: Optional[str] = None,
    used_tools: Optional[List[str]] = None,
    max_suggestions: int = 3,
    min_similarity: float = 0.4,
    current_task: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    Get suggestions for tools that might be helpful for a query.

    Use this to discover tools you might have missed or forgotten.

    Args:
        query: The user query or task description
        current_task: Alias for query (accepted for compatibility)
        used_tools: List of tools already used (will be excluded)
        max_suggestions: Maximum number of suggestions to return
        min_similarity: Minimum similarity threshold (0.0-1.0)

    Returns:
        Dict with suggestions and formatted output
    """
    try:
        if not query:
            query = current_task
        if not query:
            return {"success": False, "error": "missing query/current_task", "suggestions": []}

        from ..services.tool_suggestions import get_tool_suggestion_service

        service = get_tool_suggestion_service()

        # Temporarily adjust threshold if needed
        original_threshold = service.__class__.SIMILARITY_THRESHOLD if hasattr(service.__class__, 'SIMILARITY_THRESHOLD') else 0.45

        suggestions = service.get_suggestions(
            query=query,
            used_tools=set(used_tools or []),
            max_suggestions=max_suggestions
        )

        # Filter by min_similarity
        suggestions = [s for s in suggestions if s.similarity >= min_similarity]

        result = {
            "success": True,
            "suggestions": [
                {
                    "tool_name": s.tool_name,
                    "description": s.description,
                    "usage_hint": s.usage_hint,
                    "similarity": round(s.similarity, 3),
                    "category": s.category
                }
                for s in suggestions
            ],
            "count": len(suggestions)
        }

        if suggestions:
            result["formatted"] = service.format_suggestions(suggestions)

        return result

    except Exception as e:
        logger.error(f"Failed to get tool suggestions: {e}")
        return {"success": False, "error": str(e), "suggestions": []}


def record_suggestion_feedback(
    tool_name: str,
    was_helpful: bool,
    query_preview: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Record feedback on whether a tool suggestion was helpful.

    Use this after trying a suggested tool to help improve future suggestions.

    Args:
        tool_name: The suggested tool that was used
        was_helpful: Whether the suggestion was actually helpful
        query_preview: Preview of the query for context
        session_id: Session ID for tracking

    Returns:
        Dict with success status
    """
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jarvis_tool_suggestion_feedback
                    (tool_name, was_helpful, query_preview, session_id, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (tool_name, was_helpful, query_preview[:200] if query_preview else None, session_id))
                conn.commit()

        logger.info(f"Recorded suggestion feedback: {tool_name} was_helpful={was_helpful}")

        return {
            "success": True,
            "tool_name": tool_name,
            "was_helpful": was_helpful
        }

    except Exception as e:
        logger.error(f"Failed to record suggestion feedback: {e}")
        return {"success": False, "error": str(e)}


def get_suggestion_stats(days: int = 30) -> Dict[str, Any]:
    """
    Get statistics on tool suggestion effectiveness.

    Use this to see which suggested tools are actually helpful.

    Args:
        days: Number of days to analyze

    Returns:
        Dict with suggestion statistics
    """
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Overall stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN was_helpful THEN 1 END) as helpful,
                        ROUND(COUNT(CASE WHEN was_helpful THEN 1 END)::float / NULLIF(COUNT(*), 0) * 100, 1) as helpful_rate
                    FROM jarvis_tool_suggestion_feedback
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))
                row = cur.fetchone()
                overall = {
                    "total_feedback": row[0] if row else 0,
                    "helpful_count": row[1] if row else 0,
                    "helpful_rate": float(row[2]) if row and row[2] else 0.0
                }

                # Per-tool breakdown
                cur.execute("""
                    SELECT
                        tool_name,
                        COUNT(*) as total,
                        COUNT(CASE WHEN was_helpful THEN 1 END) as helpful,
                        ROUND(COUNT(CASE WHEN was_helpful THEN 1 END)::float / NULLIF(COUNT(*), 0) * 100, 1) as helpful_rate
                    FROM jarvis_tool_suggestion_feedback
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY tool_name
                    ORDER BY total DESC
                    LIMIT 20
                """, (days,))

                per_tool = []
                for row in cur.fetchall():
                    per_tool.append({
                        "tool_name": row[0],
                        "total": row[1],
                        "helpful": row[2],
                        "helpful_rate": float(row[3]) if row[3] else 0.0
                    })

        return {
            "success": True,
            "days": days,
            "overall": overall,
            "per_tool": per_tool
        }

    except Exception as e:
        logger.error(f"Failed to get suggestion stats: {e}")
        return {"success": False, "error": str(e)}


def list_underused_tools(
    min_use_count: int = 0,
    max_use_count: int = 5,
    category: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    List tools that are rarely used but might be valuable.

    Use this to discover tools you might not know about.

    Args:
        min_use_count: Minimum use count
        max_use_count: Maximum use count
        category: Filter by category
        limit: Maximum number of tools to return

    Returns:
        Dict with underused tools
    """
    try:
        from ..postgres_state import get_dict_cursor

        with get_dict_cursor() as cur:
            query_sql = """
                SELECT name, description, usage_hint, category, use_count
                FROM jarvis_tools
                WHERE enabled = true
                  AND use_count >= %s
                  AND use_count <= %s
            """
            params = [min_use_count, max_use_count]

            if category:
                query_sql += " AND category = %s"
                params.append(category)

            query_sql += " ORDER BY use_count ASC, name LIMIT %s"
            params.append(limit)

            cur.execute(query_sql, params)

            tools = []
            for row in cur.fetchall():
                tools.append({
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "usage_hint": row.get("usage_hint"),
                    "category": row.get("category"),
                    "use_count": row.get("use_count", 0)
                })

        return {
            "success": True,
            "tools": tools,
            "count": len(tools),
            "filter": {
                "min_use_count": min_use_count,
                "max_use_count": max_use_count,
                "category": category
            }
        }

    except Exception as e:
        logger.error(f"Failed to list underused tools: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for registration
TOOLS = [
    {
        "name": "get_tool_suggestions",
        "description": "Get suggestions for tools that might be helpful for a query. Discovers tools you might have missed.",
        "function": get_tool_suggestions,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user query or task description"
                },
                "used_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tools already used (will be excluded)"
                },
                "max_suggestions": {
                    "type": "integer",
                    "default": 3,
                    "description": "Maximum number of suggestions"
                },
                "min_similarity": {
                    "type": "number",
                    "default": 0.4,
                    "description": "Minimum similarity threshold (0.0-1.0)"
                }
            },
            "required": ["query"]
        },
        "category": "meta",
        "risk_tier": 0
    },
    {
        "name": "record_suggestion_feedback",
        "description": "Record feedback on whether a tool suggestion was helpful",
        "function": record_suggestion_feedback,
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The suggested tool that was used"
                },
                "was_helpful": {
                    "type": "boolean",
                    "description": "Whether the suggestion was actually helpful"
                },
                "query_preview": {
                    "type": "string",
                    "description": "Preview of the query for context"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for tracking"
                }
            },
            "required": ["tool_name", "was_helpful"]
        },
        "category": "meta",
        "risk_tier": 0
    },
    {
        "name": "get_suggestion_stats",
        "description": "Get statistics on tool suggestion effectiveness",
        "function": get_suggestion_stats,
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "default": 30,
                    "description": "Number of days to analyze"
                }
            }
        },
        "category": "meta",
        "risk_tier": 0
    },
    {
        "name": "list_underused_tools",
        "description": "List tools that are rarely used but might be valuable",
        "function": list_underused_tools,
        "parameters": {
            "type": "object",
            "properties": {
                "min_use_count": {
                    "type": "integer",
                    "default": 0,
                    "description": "Minimum use count"
                },
                "max_use_count": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum use count"
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category"
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of tools to return"
                }
            }
        },
        "category": "meta",
        "risk_tier": 0
    }
]
