"""
Tool Categories Service - Phase 21 Option 2C

Provides compact tool category summaries for the system prompt.
Instead of listing 400+ tools, shows categories with counts.
Tools can be expanded on-demand via list_category_tools.
"""
from typing import Dict, Any, List, Optional
from functools import lru_cache
import time

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.tool_categories")

# Cache TTL for category data
_CACHE_TTL_SECONDS = 300
_category_cache: Dict[str, Any] = {}
_cache_timestamp: float = 0


def _load_categories_from_db() -> Dict[str, Dict[str, Any]]:
    """Load tool categories from database with counts."""
    global _category_cache, _cache_timestamp

    now = time.time()
    if _category_cache and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        return _category_cache

    try:
        from ..postgres_state import get_dict_cursor

        with get_dict_cursor() as cur:
            # Get category counts and sample tools
            cur.execute("""
                SELECT
                    jt.category,
                    COUNT(*) as tool_count,
                    (
                        SELECT ARRAY(
                            SELECT t2.name
                            FROM jarvis_tools t2
                            WHERE t2.enabled = true
                              AND COALESCE(t2.category, 'general') = COALESCE(jt.category, 'general')
                            ORDER BY t2.use_count DESC, t2.name ASC
                            LIMIT 5
                        )
                    ) as top_tools,
                    ARRAY_AGG(DISTINCT jt.keywords) FILTER (WHERE jt.keywords IS NOT NULL) as all_keywords
                FROM jarvis_tools jt
                WHERE jt.enabled = true
                GROUP BY jt.category
                ORDER BY tool_count DESC
            """)

            categories = {}
            for row in cur.fetchall():
                cat_name = row.get("category") or "general"
                top_tools = row.get("top_tools") or []
                all_keywords = row.get("all_keywords") or []
                categories[cat_name] = {
                    "count": row.get("tool_count", 0),
                    "top_tools": top_tools[:5],
                    "keywords": _flatten_keywords(all_keywords)
                }

            _category_cache = categories
            _cache_timestamp = now

            log_with_context(
                logger, "debug", "Loaded tool categories",
                category_count=len(categories),
                total_tools=sum(c["count"] for c in categories.values())
            )

            return categories

    except Exception as e:
        log_with_context(logger, "warning", "Failed to load categories from DB", error=str(e))
        return _get_fallback_categories()


def _flatten_keywords(nested_arrays) -> List[str]:
    """Flatten nested keyword arrays and deduplicate."""
    if not nested_arrays:
        return []

    flat = set()
    for arr in nested_arrays:
        if arr:
            if isinstance(arr, list):
                flat.update(arr)
            else:
                flat.add(str(arr))

    return sorted(list(flat))[:10]  # Max 10 keywords per category


def _get_fallback_categories() -> Dict[str, Dict[str, Any]]:
    """Fallback categories if DB is unavailable."""
    return {
        "memory": {"count": 15, "top_tools": ["remember_fact", "recall_facts", "search_knowledge"], "keywords": ["erinnern", "speichern"]},
        "calendar": {"count": 8, "top_tools": ["get_calendar_events", "create_calendar_event"], "keywords": ["termin", "kalender"]},
        "email": {"count": 6, "top_tools": ["get_gmail_messages", "send_email"], "keywords": ["email", "mail"]},
        "project": {"count": 12, "top_tools": ["list_projects", "add_project", "get_asana_tasks"], "keywords": ["projekt", "task"]},
        "research": {"count": 10, "top_tools": ["research_topic", "web_search"], "keywords": ["recherche", "suche"]},
        "system": {"count": 20, "top_tools": ["system_health_check", "get_config"], "keywords": ["system", "health"]},
        "learning": {"count": 8, "top_tools": ["record_learning", "get_learnings"], "keywords": ["lernen", "learning"]},
        "verification": {"count": 6, "top_tools": ["verify_fact", "check_corrections"], "keywords": ["prüfen", "verify"]},
        "meta": {"count": 10, "top_tools": ["list_available_tools", "get_tool_usage"], "keywords": ["tools", "meta"]},
    }


def get_compact_category_summary() -> str:
    """
    Generate a compact category summary for the system prompt.

    Returns a string like:
    Du hast Zugriff auf 415 Tools in diesen Kategorien:
    - Memory & Knowledge (45): erinnern, speichern, wissen
    - Calendar (8): termine, events, planung
    ...
    Sage "list_category_tools('memory')" für Details.
    """
    categories = _load_categories_from_db()

    if not categories:
        return ""

    total_tools = sum(c["count"] for c in categories.values())

    lines = [f"\n## Verfügbare Tools ({total_tools} gesamt)\n"]
    lines.append("Du hast Zugriff auf diese Tool-Kategorien:\n")

    # Sort by count descending
    sorted_cats = sorted(categories.items(), key=lambda x: -x[1]["count"])

    for cat_name, data in sorted_cats[:15]:  # Top 15 categories
        count = data["count"]
        keywords = ", ".join(data["keywords"][:3]) if data["keywords"] else ""
        top_tools = ", ".join(data["top_tools"][:2]) if data["top_tools"] else ""

        # Format: Category (count): keywords [examples: tool1, tool2]
        if keywords and top_tools:
            lines.append(f"- **{cat_name}** ({count}): {keywords} [z.B. {top_tools}]")
        elif top_tools:
            lines.append(f"- **{cat_name}** ({count}): {top_tools}")
        else:
            lines.append(f"- **{cat_name}** ({count})")

    lines.append("\n💡 Nutze `list_category_tools('kategorie')` für Details zu einer Kategorie.")

    return "\n".join(lines)


def list_tools_in_category(category: str, include_unused: bool = False) -> Dict[str, Any]:
    """
    List all tools in a specific category.

    Args:
        category: Category name to list
        include_unused: Include tools with 0 use count

    Returns:
        Dict with tools in the category
    """
    try:
        from ..postgres_state import get_dict_cursor

        with get_dict_cursor() as cur:
            query_sql = """
                SELECT name, description, usage_hint, use_count, risk_tier
                FROM jarvis_tools
                WHERE enabled = true
                  AND category = %s
            """
            params = [category]

            if not include_unused:
                query_sql += " AND use_count > 0"

            query_sql += " ORDER BY use_count DESC, name"

            cur.execute(query_sql, params)

            tools = []
            for row in cur.fetchall():
                desc = row.get("description") or ""
                tools.append({
                    "name": row.get("name"),
                    "description": desc[:100],
                    "usage_hint": row.get("usage_hint") or "",
                    "use_count": row.get("use_count", 0),
                    "risk_tier": row.get("risk_tier")
                })

        return {
            "success": True,
            "category": category,
            "tools": tools,
            "count": len(tools)
        }

    except Exception as e:
        logger.error(f"Failed to list tools in category: {e}")
        return {"success": False, "error": str(e), "tools": []}


def get_all_categories() -> Dict[str, Any]:
    """Get all available categories with counts."""
    categories = _load_categories_from_db()

    return {
        "success": True,
        "categories": [
            {
                "name": name,
                "count": data["count"],
                "top_tools": data["top_tools"][:3],
                "keywords": data["keywords"][:5]
            }
            for name, data in sorted(categories.items(), key=lambda x: -x[1]["count"])
        ],
        "total_categories": len(categories),
        "total_tools": sum(c["count"] for c in categories.values())
    }


def search_tools_by_keyword(keyword: str, limit: int = 10) -> Dict[str, Any]:
    """
    Search for tools by keyword in name, description, or keywords array.

    Args:
        keyword: Search keyword
        limit: Maximum results

    Returns:
        Dict with matching tools
    """
    try:
        from ..postgres_state import get_dict_cursor

        keyword_lower = keyword.lower()

        with get_dict_cursor() as cur:
            cur.execute("""
                SELECT name, description, usage_hint, category, use_count
                FROM jarvis_tools
                WHERE enabled = true
                  AND (
                      LOWER(name) LIKE %s
                      OR LOWER(COALESCE(description, '')) LIKE %s
                      OR LOWER(COALESCE(usage_hint, '')) LIKE %s
                      OR %s = ANY(COALESCE(keywords, ARRAY[]::text[]))
                  )
                ORDER BY use_count DESC
                LIMIT %s
            """, (
                f"%{keyword_lower}%",
                f"%{keyword_lower}%",
                f"%{keyword_lower}%",
                keyword_lower,
                limit
            ))

            tools = []
            for row in cur.fetchall():
                desc = row.get("description") or ""
                tools.append({
                    "name": row.get("name"),
                    "description": desc[:100],
                    "usage_hint": row.get("usage_hint") or "",
                    "category": row.get("category"),
                    "use_count": row.get("use_count", 0)
                })

        return {
            "success": True,
            "keyword": keyword,
            "tools": tools,
            "count": len(tools)
        }

    except Exception as e:
        logger.error(f"Failed to search tools: {e}")
        return {"success": False, "error": str(e), "tools": []}


def invalidate_category_cache():
    """Force cache refresh on next access."""
    global _cache_timestamp
    _cache_timestamp = 0
