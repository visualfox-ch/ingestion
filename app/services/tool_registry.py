"""
Tool Registry Service - DEPRECATED (Phase C3)

This module is now a thin wrapper around tool_autonomy.py (PostgreSQL).
The SQLite-based registry is deprecated. All queries are redirected to PostgreSQL.

Migration: 2026-03-18
Reason: Single source of truth in PostgreSQL, Jarvis can self-manage tools
"""
from __future__ import annotations

import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.tool_registry")

# Emit deprecation warning on import
warnings.warn(
    "tool_registry (SQLite) is deprecated. Use tool_autonomy (PostgreSQL) directly.",
    DeprecationWarning,
    stacklevel=2
)


def _get_autonomy_service():
    """Get the PostgreSQL-backed tool autonomy service."""
    from .tool_autonomy import get_tool_autonomy_service
    return get_tool_autonomy_service()


def _get_conn():
    """
    DEPRECATED: SQLite connection is no longer used.
    Kept for backward compatibility with any code that checks for this function.
    """
    raise DeprecationWarning(
        "SQLite tool_registry is deprecated. Use tool_autonomy service instead."
    )


def sync_tools_from_code(tool_definitions: List[Dict]) -> Dict[str, Any]:
    """
    Sync tool definitions from code to database.
    Now delegates to PostgreSQL via tool_autonomy service.
    """
    try:
        service = _get_autonomy_service()
        result = service.sync_tools_from_code(tool_definitions)

        # Convert response format for backward compatibility
        if result.get("status") == "synced":
            return {"synced": result.get("count", 0), "new_tools": 0}
        elif result.get("status") == "error":
            return {"error": result.get("error")}
        return result

    except Exception as e:
        log_with_context(logger, "error", "Tool registry sync failed", error=str(e))
        return {"error": str(e)}


def is_tool_enabled(tool_name: str) -> bool:
    """Check if a tool is enabled."""
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT enabled FROM jarvis_tools WHERE name = %s",
                    (tool_name,)
                )
                row = cur.fetchone()
                if row is None:
                    return True  # Unknown tools enabled by default
                return bool(row[0] if isinstance(row, tuple) else row.get("enabled", True))
    except Exception:
        return True  # Default to enabled on error


def set_tool_enabled(tool_name: str, enabled: bool, reason: str = None) -> bool:
    """Enable or disable a tool."""
    try:
        service = _get_autonomy_service()
        result = service.set_tool_enabled(tool_name, enabled, reason)
        return result.get("status") == "success"
    except Exception as e:
        log_with_context(logger, "error", "Failed to set tool status", error=str(e))
        return False


def get_enabled_tools() -> List[str]:
    """Get list of enabled tool names."""
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM jarvis_tools WHERE enabled = true")
                rows = cur.fetchall()
                return [row[0] if isinstance(row, tuple) else row["name"] for row in rows]
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get enabled tools", error=str(e))
        return []


def get_disabled_tools() -> List[Dict[str, Any]]:
    """Get list of disabled tools with reasons."""
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, updated_at
                    FROM jarvis_tools
                    WHERE enabled = false
                """)
                rows = cur.fetchall()
                return [
                    {
                        "name": row[0] if isinstance(row, tuple) else row["name"],
                        "disabled_reason": None,  # Not tracked in new schema
                        "updated_at": (row[1] if isinstance(row, tuple) else row["updated_at"]).isoformat() if row else None
                    }
                    for row in rows
                ]
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get disabled tools", error=str(e))
        return []


def record_tool_usage(tool_name: str, success: bool, latency_ms: float = None) -> None:
    """Record tool usage for statistics."""
    try:
        service = _get_autonomy_service()
        service.record_tool_execution(
            tool_name=tool_name,
            success=success,
            latency_ms=int(latency_ms) if latency_ms else 0
        )
    except Exception as e:
        log_with_context(logger, "debug", "Failed to record tool usage", error=str(e))


def get_tool_stats(category: str = None, min_usage: int = 0) -> List[Dict[str, Any]]:
    """Get tool usage statistics."""
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT name, category, enabled, use_count,
                           COALESCE(success_rate * 100, 0) as success_rate,
                           COALESCE(avg_latency_ms, 0) as avg_latency_ms
                    FROM jarvis_tools
                    WHERE use_count >= %s
                """
                params = [min_usage]

                if category:
                    sql += " AND category = %s"
                    params.append(category)

                sql += " ORDER BY use_count DESC"

                cur.execute(sql, params)
                rows = cur.fetchall()

                return [
                    {
                        "name": row[0] if isinstance(row, tuple) else row["name"],
                        "category": row[1] if isinstance(row, tuple) else row["category"],
                        "enabled": row[2] if isinstance(row, tuple) else row["enabled"],
                        "usage_count": row[3] if isinstance(row, tuple) else row["use_count"],
                        "success_count": 0,  # Not tracked separately
                        "success_rate": float(row[4] if isinstance(row, tuple) else row["success_rate"]),
                        "avg_latency_ms": float(row[5] if isinstance(row, tuple) else row["avg_latency_ms"])
                    }
                    for row in rows
                ]
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get tool stats", error=str(e))
        return []


def get_unused_tools(days: int = 7) -> List[str]:
    """Get tools that haven't been used recently."""
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name FROM jarvis_tools
                    WHERE use_count = 0
                       OR last_used_at IS NULL
                       OR last_used_at < NOW() - INTERVAL '%s days'
                    ORDER BY use_count ASC
                    LIMIT 20
                """, (days,))
                rows = cur.fetchall()
                return [row[0] if isinstance(row, tuple) else row["name"] for row in rows]
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get unused tools", error=str(e))
        return []


def get_registry_summary() -> Dict[str, Any]:
    """Get summary of tool registry."""
    try:
        from ..postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Total tools
                cur.execute("SELECT COUNT(*) FROM jarvis_tools")
                total = cur.fetchone()[0]

                # Enabled/disabled
                cur.execute("SELECT COUNT(*) FROM jarvis_tools WHERE enabled = true")
                enabled = cur.fetchone()[0]

                # By category
                cur.execute("""
                    SELECT category, COUNT(*) as cnt
                    FROM jarvis_tools
                    GROUP BY category
                    ORDER BY cnt DESC
                """)
                by_category = {
                    row[0] if isinstance(row, tuple) else row["category"]:
                    row[1] if isinstance(row, tuple) else row["cnt"]
                    for row in cur.fetchall()
                }

                # Most used
                cur.execute("""
                    SELECT name, use_count
                    FROM jarvis_tools
                    ORDER BY use_count DESC
                    LIMIT 5
                """)
                most_used = [
                    {
                        "name": row[0] if isinstance(row, tuple) else row["name"],
                        "count": row[1] if isinstance(row, tuple) else row["use_count"]
                    }
                    for row in cur.fetchall()
                ]

                # By risk tier
                cur.execute("""
                    SELECT risk_tier, COUNT(*) as cnt
                    FROM jarvis_tools
                    GROUP BY risk_tier
                    ORDER BY risk_tier
                """)
                by_risk_tier = {
                    f"tier_{row[0] if isinstance(row, tuple) else row['risk_tier']}":
                    row[1] if isinstance(row, tuple) else row["cnt"]
                    for row in cur.fetchall()
                }

                return {
                    "total_tools": total,
                    "enabled": enabled,
                    "disabled": total - enabled,
                    "by_category": by_category,
                    "by_risk_tier": by_risk_tier,
                    "most_used": most_used,
                    "source": "postgresql"  # Indicate new source
                }
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get registry summary", error=str(e))
        return {"error": str(e)}


def _categorize_tool(name: str) -> str:
    """
    Auto-categorize tool based on name.
    DEPRECATED: Categories are now managed in the database.
    """
    categories = {
        "memory": ["remember", "recall", "fact", "knowledge"],
        "calendar": ["calendar", "event"],
        "email": ["email", "gmail", "mail"],
        "search": ["search", "find", "query"],
        "project": ["project", "task", "thread"],
        "file": ["file", "read", "write", "code"],
        "system": ["health", "validation", "diagnostic", "pulse"],
        "llm": ["ollama", "delegate", "subagent"],
        "self_mod": ["dynamic", "sandbox", "write_tool", "promote"],
        "orchestration": ["route", "teammate", "spawn", "inbox", "message", "compact", "schedule"],
        "learning": ["improvement", "suggest_improvement", "review_improvement", "record_learning", "get_learnings"],
        "extended_memory": ["store_context", "recall_context", "forget_context"],
        "automation": ["trigger", "execute_trigger", "list_trigger"],
    }

    name_lower = name.lower()
    for category, keywords in categories.items():
        if any(kw in name_lower for kw in keywords):
            return category
    return "general"
