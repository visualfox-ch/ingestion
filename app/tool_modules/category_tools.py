"""
Tool Category Tools - Phase 21 Option 2C

Tools for exploring and discovering tools by category.
"""
from typing import Dict, Any, List, Optional

from ..observability import get_logger

logger = get_logger("jarvis.tools.categories")


def list_category_tools(
    category: str,
    include_unused: bool = True
) -> Dict[str, Any]:
    """
    List all tools in a specific category.

    Use this to discover tools in a category when you need specific functionality.

    Args:
        category: Category name (e.g., "memory", "calendar", "email")
        include_unused: Include tools that have never been used

    Returns:
        Dict with tools in the category
    """
    try:
        from ..services.tool_categories import list_tools_in_category

        result = list_tools_in_category(category, include_unused)

        if result.get("success") and result.get("tools"):
            # Format for easy reading
            formatted = f"\n**Tools in '{category}' ({result['count']}):**\n"
            for t in result["tools"]:
                hint = t.get("usage_hint") or t.get("description", "")[:60]
                formatted += f"- `{t['name']}`: {hint}\n"
            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed to list category tools: {e}")
        return {"success": False, "error": str(e)}


def get_tool_categories() -> Dict[str, Any]:
    """
    Get all available tool categories with counts.

    Use this to see what tool categories exist before diving deeper.

    Returns:
        Dict with all categories and their tool counts
    """
    try:
        from ..services.tool_categories import get_all_categories

        result = get_all_categories()

        if result.get("success"):
            # Format for easy reading
            formatted = f"\n**Tool-Kategorien ({result['total_categories']} Kategorien, {result['total_tools']} Tools):**\n"
            for cat in result["categories"][:20]:
                tools_preview = ", ".join(cat["top_tools"][:2]) if cat["top_tools"] else ""
                if tools_preview:
                    formatted += f"- **{cat['name']}** ({cat['count']}): {tools_preview}\n"
                else:
                    formatted += f"- **{cat['name']}** ({cat['count']})\n"
            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed to get tool categories: {e}")
        return {"success": False, "error": str(e)}


def search_tools(
    keyword: str,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Search for tools by keyword.

    Searches in tool names, descriptions, usage hints, and keywords.

    Args:
        keyword: Search keyword
        limit: Maximum number of results

    Returns:
        Dict with matching tools
    """
    try:
        from ..services.tool_categories import search_tools_by_keyword

        result = search_tools_by_keyword(keyword, limit)

        if result.get("success") and result.get("tools"):
            formatted = f"\n**Tools matching '{keyword}' ({result['count']}):**\n"
            for t in result["tools"]:
                hint = t.get("usage_hint") or t.get("description", "")[:60]
                formatted += f"- `{t['name']}` [{t['category']}]: {hint}\n"
            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed to search tools: {e}")
        return {"success": False, "error": str(e)}


def get_recommended_tools(
    context: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 5
) -> Dict[str, Any]:
    """
    Get recommended tools based on context or task type.

    Combines category knowledge with usage patterns to suggest relevant tools.

    Args:
        context: Current context or query
        task_type: Type of task (research, communication, memory, etc.)
        limit: Maximum recommendations

    Returns:
        Dict with recommended tools
    """
    try:
        from ..postgres_state import get_conn

        recommendations = []

        with get_conn() as conn:
            with conn.cursor() as cur:
                if task_type:
                    # Get tools from matching category
                    cur.execute("""
                        SELECT name, description, usage_hint, category, use_count
                        FROM jarvis_tools
                        WHERE enabled = true
                          AND category = %s
                        ORDER BY use_count DESC
                        LIMIT %s
                    """, (task_type, limit))
                elif context:
                    # Search based on context keywords
                    from ..services.tool_categories import search_tools_by_keyword
                    # Extract first significant word
                    words = [w for w in context.lower().split() if len(w) > 3][:3]
                    for word in words:
                        result = search_tools_by_keyword(word, limit=3)
                        if result.get("tools"):
                            recommendations.extend(result["tools"])
                            if len(recommendations) >= limit:
                                break
                else:
                    # Get most versatile tools (high usage, multiple categories)
                    cur.execute("""
                        SELECT name, description, usage_hint, category, use_count
                        FROM jarvis_tools
                        WHERE enabled = true
                          AND use_count > 10
                        ORDER BY use_count DESC
                        LIMIT %s
                    """, (limit,))

                if not recommendations:
                    for row in cur.fetchall():
                        recommendations.append({
                            "name": row[0],
                            "description": row[1][:100] if row[1] else "",
                            "usage_hint": row[2] or "",
                            "category": row[3],
                            "use_count": row[4]
                        })

        # Deduplicate
        seen = set()
        unique_recs = []
        for r in recommendations:
            if r["name"] not in seen:
                seen.add(r["name"])
                unique_recs.append(r)

        result = {
            "success": True,
            "recommendations": unique_recs[:limit],
            "count": len(unique_recs[:limit]),
            "context": context,
            "task_type": task_type
        }

        if unique_recs:
            formatted = "\n**Empfohlene Tools:**\n"
            for t in unique_recs[:limit]:
                hint = t.get("usage_hint") or t.get("description", "")[:60]
                formatted += f"- `{t['name']}`: {hint}\n"
            result["formatted"] = formatted

        return result

    except Exception as e:
        logger.error(f"Failed to get recommended tools: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for registration
TOOLS = [
    {
        "name": "list_category_tools",
        "description": "List all tools in a specific category. Use to discover available tools.",
        "function": list_category_tools,
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category name (e.g., 'memory', 'calendar', 'email', 'research')"
                },
                "include_unused": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include tools that have never been used"
                }
            },
            "required": ["category"]
        },
        "category": "meta",
        "risk_tier": 0
    },
    {
        "name": "get_tool_categories",
        "description": "Get all available tool categories with counts. Overview of all tool capabilities.",
        "function": get_tool_categories,
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "category": "meta",
        "risk_tier": 0
    },
    {
        "name": "search_tools",
        "description": "Search for tools by keyword in names, descriptions, and hints",
        "function": search_tools,
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword"
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of results"
                }
            },
            "required": ["keyword"]
        },
        "category": "meta",
        "risk_tier": 0
    },
    {
        "name": "get_recommended_tools",
        "description": "Get recommended tools based on context or task type",
        "function": get_recommended_tools,
        "parameters": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Current context or query"
                },
                "task_type": {
                    "type": "string",
                    "description": "Type of task (research, communication, memory, etc.)"
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum recommendations"
                }
            }
        },
        "category": "meta",
        "risk_tier": 0
    }
]
