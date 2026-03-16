"""
Tool Registry Service - Phase 19.5

Database-backed tool registry that allows:
- Enabling/disabling tools without deploy
- Storing tool metadata and usage stats
- Jarvis self-managing his toolset

Tables:
- tool_registry: Tool definitions and status
- tool_usage_stats: Aggregated usage statistics
"""
from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from threading import Lock

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.tool_registry")

# Database path
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
REGISTRY_DB_PATH = BRAIN_ROOT / "system" / "state" / "tool_registry.db"

_db_lock = Lock()


def _get_conn() -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    REGISTRY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(REGISTRY_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tool_registry (
            name TEXT PRIMARY KEY,
            description TEXT,
            category TEXT DEFAULT 'general',
            enabled BOOLEAN DEFAULT 1,
            source TEXT DEFAULT 'code',
            schema_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            disabled_reason TEXT,
            usage_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            avg_latency_ms REAL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_tool_enabled ON tool_registry(enabled);
        CREATE INDEX IF NOT EXISTS idx_tool_category ON tool_registry(category);

        CREATE TABLE IF NOT EXISTS tool_overrides (
            tool_name TEXT PRIMARY KEY,
            override_type TEXT NOT NULL,
            override_value TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT DEFAULT 'system'
        );
    """)
    conn.commit()
    return conn


def sync_tools_from_code(tool_definitions: List[Dict]) -> Dict[str, Any]:
    """
    Sync tool definitions from code to database.
    Called at startup to ensure DB has all tools.
    """
    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()

            synced = 0
            new_tools = 0

            for tool in tool_definitions:
                name = tool.get("name")
                if not name:
                    continue

                # Check if tool exists
                cursor = conn.execute(
                    "SELECT name, enabled FROM tool_registry WHERE name = ?",
                    (name,)
                )
                existing = cursor.fetchone()

                if existing:
                    # Update description but keep enabled status
                    conn.execute("""
                        UPDATE tool_registry
                        SET description = ?, schema_json = ?, updated_at = ?
                        WHERE name = ?
                    """, (
                        tool.get("description", "")[:500],
                        json.dumps(tool.get("input_schema", {})),
                        now,
                        name
                    ))
                    synced += 1
                else:
                    # New tool
                    conn.execute("""
                        INSERT INTO tool_registry
                        (name, description, category, enabled, source, schema_json, created_at, updated_at)
                        VALUES (?, ?, ?, 1, 'code', ?, ?, ?)
                    """, (
                        name,
                        tool.get("description", "")[:500],
                        _categorize_tool(name),
                        json.dumps(tool.get("input_schema", {})),
                        now, now
                    ))
                    new_tools += 1

            conn.commit()
            conn.close()

            log_with_context(logger, "info", "Tool registry synced",
                           synced=synced, new_tools=new_tools)
            return {"synced": synced, "new_tools": new_tools}
        except Exception as e:
            log_with_context(logger, "error", "Tool registry sync failed", error=str(e))
            return {"error": str(e)}


def _categorize_tool(name: str) -> str:
    """Auto-categorize tool based on name."""
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


def is_tool_enabled(tool_name: str) -> bool:
    """Check if a tool is enabled."""
    try:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT enabled FROM tool_registry WHERE name = ?",
            (tool_name,)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return True  # Unknown tools are enabled by default
        return bool(row["enabled"])
    except Exception:
        return True  # Default to enabled on error


def set_tool_enabled(tool_name: str, enabled: bool, reason: str = None) -> bool:
    """Enable or disable a tool."""
    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()

            conn.execute("""
                UPDATE tool_registry
                SET enabled = ?, disabled_reason = ?, updated_at = ?
                WHERE name = ?
            """, (enabled, reason if not enabled else None, now, tool_name))

            conn.commit()
            affected = conn.total_changes
            conn.close()

            log_with_context(logger, "info", "Tool status changed",
                           tool=tool_name, enabled=enabled, reason=reason)
            return affected > 0
        except Exception as e:
            log_with_context(logger, "error", "Failed to set tool status", error=str(e))
            return False


def get_enabled_tools() -> List[str]:
    """Get list of enabled tool names."""
    try:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT name FROM tool_registry WHERE enabled = 1"
        )
        tools = [row["name"] for row in cursor.fetchall()]
        conn.close()
        return tools
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get enabled tools", error=str(e))
        return []


def get_disabled_tools() -> List[Dict[str, Any]]:
    """Get list of disabled tools with reasons."""
    try:
        conn = _get_conn()
        cursor = conn.execute("""
            SELECT name, disabled_reason, updated_at
            FROM tool_registry
            WHERE enabled = 0
        """)
        tools = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tools
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get disabled tools", error=str(e))
        return []


def record_tool_usage(tool_name: str, success: bool, latency_ms: float = None) -> None:
    """Record tool usage for statistics."""
    with _db_lock:
        try:
            conn = _get_conn()

            # Update aggregated stats
            if success:
                conn.execute("""
                    UPDATE tool_registry
                    SET usage_count = usage_count + 1,
                        success_count = success_count + 1,
                        avg_latency_ms = CASE
                            WHEN usage_count = 0 THEN ?
                            ELSE (avg_latency_ms * usage_count + ?) / (usage_count + 1)
                        END
                    WHERE name = ?
                """, (latency_ms or 0, latency_ms or 0, tool_name))
            else:
                conn.execute("""
                    UPDATE tool_registry
                    SET usage_count = usage_count + 1
                    WHERE name = ?
                """, (tool_name,))

            conn.commit()
            conn.close()
        except Exception as e:
            log_with_context(logger, "debug", "Failed to record tool usage", error=str(e))


def get_tool_stats(category: str = None, min_usage: int = 0) -> List[Dict[str, Any]]:
    """Get tool usage statistics."""
    try:
        conn = _get_conn()

        sql = """
            SELECT name, category, enabled, usage_count, success_count,
                   CASE WHEN usage_count > 0 THEN ROUND(success_count * 100.0 / usage_count, 1) ELSE 0 END as success_rate,
                   ROUND(avg_latency_ms, 1) as avg_latency_ms
            FROM tool_registry
            WHERE usage_count >= ?
        """
        params = [min_usage]

        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " ORDER BY usage_count DESC"

        cursor = conn.execute(sql, params)
        stats = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return stats
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get tool stats", error=str(e))
        return []


def get_unused_tools(days: int = 7) -> List[str]:
    """Get tools that haven't been used recently."""
    try:
        conn = _get_conn()
        cursor = conn.execute("""
            SELECT name FROM tool_registry
            WHERE usage_count = 0
            OR updated_at < datetime('now', ?)
            ORDER BY usage_count ASC
            LIMIT 20
        """, (f"-{days} days",))
        tools = [row["name"] for row in cursor.fetchall()]
        conn.close()
        return tools
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get unused tools", error=str(e))
        return []


def get_registry_summary() -> Dict[str, Any]:
    """Get summary of tool registry."""
    try:
        conn = _get_conn()

        # Total tools
        cursor = conn.execute("SELECT COUNT(*) as total FROM tool_registry")
        total = cursor.fetchone()["total"]

        # Enabled/disabled
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM tool_registry WHERE enabled = 1")
        enabled = cursor.fetchone()["cnt"]

        # By category
        cursor = conn.execute("""
            SELECT category, COUNT(*) as cnt
            FROM tool_registry
            GROUP BY category
            ORDER BY cnt DESC
        """)
        by_category = {row["category"]: row["cnt"] for row in cursor.fetchall()}

        # Most used
        cursor = conn.execute("""
            SELECT name, usage_count
            FROM tool_registry
            ORDER BY usage_count DESC
            LIMIT 5
        """)
        most_used = [{"name": row["name"], "count": row["usage_count"]} for row in cursor.fetchall()]

        conn.close()

        return {
            "total_tools": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "by_category": by_category,
            "most_used": most_used
        }
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get registry summary", error=str(e))
        return {"error": str(e)}
