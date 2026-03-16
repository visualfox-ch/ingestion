"""
Prompt Fragments Service - Phase 19.5

Database-backed prompt fragments that allow:
- Storing reusable prompt pieces
- Jarvis modifying his own behavior/personality
- A/B testing different prompts
- Version history of prompts

Tables:
- prompt_fragments: Individual prompt pieces
- prompt_profiles: Complete prompt configurations
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from threading import Lock

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.prompt_fragments")

# Database path
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
PROMPTS_DB_PATH = BRAIN_ROOT / "system" / "state" / "prompt_fragments.db"

_db_lock = Lock()


def _get_conn() -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    PROMPTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PROMPTS_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prompt_fragments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            description TEXT,
            priority INTEGER DEFAULT 50,
            enabled BOOLEAN DEFAULT 1,
            conditions TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by TEXT DEFAULT 'system',
            version INTEGER DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_fragment_category ON prompt_fragments(category);
        CREATE INDEX IF NOT EXISTS idx_fragment_enabled ON prompt_fragments(enabled);

        CREATE TABLE IF NOT EXISTS prompt_profiles (
            name TEXT PRIMARY KEY,
            description TEXT,
            fragments TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prompt_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fragment_name TEXT NOT NULL,
            old_content TEXT,
            new_content TEXT,
            changed_at TEXT NOT NULL,
            changed_by TEXT DEFAULT 'system',
            reason TEXT
        );
    """)
    conn.commit()
    return conn


def init_default_fragments() -> Dict[str, Any]:
    """Initialize default prompt fragments from JARVIS_SELF.md etc."""
    defaults = [
        {
            "name": "core_identity",
            "category": "identity",
            "content": """Du bist Jarvis, der persoenliche AI-Assistent von Micha.
- Proaktiv, direkt, loesungsorientiert
- Deutsch als Hauptsprache, Englisch bei Bedarf
- Kurz und praegnant, keine unnoetige Hoeflichkeit
- Ehrlich auch bei unbequemen Wahrheiten""",
            "description": "Core identity and personality",
            "priority": 100
        },
        {
            "name": "communication_style",
            "category": "style",
            "content": """Kommunikationsstil:
- Antworte immer auf Basis vorhandener Daten wenn moeglich
- Bei Unsicherheit: frage nach oder sage es offen
- Keine erfundenen Fakten oder halluzinierte Quellen
- HITL: Vorschlagen ja, automatisch aendern nein""",
            "description": "How Jarvis communicates",
            "priority": 90
        },
        {
            "name": "tool_usage",
            "category": "behavior",
            "content": """Tool-Nutzung:
- Nutze Tools um Informationen zu finden bevor du spekulierst
- Nutze search_knowledge bei Wissensfragen
- Bei komplexen Tasks: Erst planen, dann ausfuehren
- Nicht unnoetig Tools aufrufen die nichts beitragen""",
            "description": "Guidelines for tool usage",
            "priority": 80
        },
        {
            "name": "self_improvement",
            "category": "capability",
            "content": """Self-Improvement Faehigkeiten:
- write_dynamic_tool: Erstelle neue Tools zur Laufzeit
- list_available_tools: Pruefe welche Tools verfuegbar sind
- Lerne aus erfolgreichen Interaktionen
- Speichere Patterns die funktionieren""",
            "description": "Self-improvement capabilities",
            "priority": 70
        },
        {
            "name": "step_management",
            "category": "behavior",
            "content": """Step-Management:
- Bei komplexen Tasks: ERST planen, DANN ausfuehren
- Wenn Step-Limit droht: Task aufteilen und User informieren
- Transparente Kommunikation statt Generic Error
- Intelligentere Priorisierung: wichtigstes Tool zuerst""",
            "description": "How to manage limited steps",
            "priority": 75
        }
    ]

    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()
            inserted = 0

            for frag in defaults:
                # Check if exists
                cursor = conn.execute(
                    "SELECT name FROM prompt_fragments WHERE name = ?",
                    (frag["name"],)
                )
                if cursor.fetchone():
                    continue

                conn.execute("""
                    INSERT INTO prompt_fragments
                    (name, category, content, description, priority, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    frag["name"], frag["category"], frag["content"],
                    frag["description"], frag["priority"], now, now
                ))
                inserted += 1

            conn.commit()
            conn.close()

            log_with_context(logger, "info", "Default fragments initialized", inserted=inserted)
            return {"inserted": inserted, "total_defaults": len(defaults)}
        except Exception as e:
            log_with_context(logger, "error", "Failed to init fragments", error=str(e))
            return {"error": str(e)}


def get_fragment(name: str) -> Optional[Dict[str, Any]]:
    """Get a specific prompt fragment."""
    try:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT * FROM prompt_fragments WHERE name = ?",
            (name,)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get fragment", name=name, error=str(e))
        return None


def get_enabled_fragments(category: str = None) -> List[Dict[str, Any]]:
    """Get all enabled fragments, optionally filtered by category."""
    try:
        conn = _get_conn()

        sql = "SELECT * FROM prompt_fragments WHERE enabled = 1"
        params = []

        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " ORDER BY priority DESC, name ASC"

        cursor = conn.execute(sql, params)
        fragments = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return fragments
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get fragments", error=str(e))
        return []


def assemble_prompt_from_fragments(categories: List[str] = None) -> str:
    """
    Assemble a complete prompt from enabled fragments.

    Args:
        categories: List of categories to include, or None for all

    Returns:
        Combined prompt string
    """
    if categories is None:
        categories = ["identity", "style", "behavior", "capability"]

    fragments = []
    for cat in categories:
        cat_fragments = get_enabled_fragments(cat)
        fragments.extend(cat_fragments)

    # Sort by priority and assemble
    fragments.sort(key=lambda x: x.get("priority", 50), reverse=True)

    parts = []
    for frag in fragments:
        content = frag.get("content", "").strip()
        if content:
            parts.append(content)

    return "\n\n".join(parts)


def update_fragment(
    name: str,
    content: str = None,
    enabled: bool = None,
    priority: int = None,
    reason: str = None,
    updated_by: str = "system"
) -> bool:
    """
    Update a prompt fragment.
    Records history for tracking changes.
    """
    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()

            # Get current content for history
            cursor = conn.execute(
                "SELECT content, version FROM prompt_fragments WHERE name = ?",
                (name,)
            )
            existing = cursor.fetchone()
            if not existing:
                conn.close()
                return False

            # Record history if content changed
            if content and content != existing["content"]:
                conn.execute("""
                    INSERT INTO prompt_history
                    (fragment_name, old_content, new_content, changed_at, changed_by, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (name, existing["content"], content, now, updated_by, reason))

            # Build update
            updates = ["updated_at = ?"]
            params = [now]

            if content is not None:
                updates.append("content = ?")
                updates.append("version = version + 1")
                params.append(content)

            if enabled is not None:
                updates.append("enabled = ?")
                params.append(enabled)

            if priority is not None:
                updates.append("priority = ?")
                params.append(priority)

            params.append(name)

            conn.execute(f"""
                UPDATE prompt_fragments
                SET {', '.join(updates)}
                WHERE name = ?
            """, params)

            conn.commit()
            conn.close()

            log_with_context(logger, "info", "Fragment updated",
                           name=name, updated_by=updated_by)
            return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to update fragment", error=str(e))
            return False


def create_fragment(
    name: str,
    category: str,
    content: str,
    description: str = None,
    priority: int = 50,
    created_by: str = "system"
) -> bool:
    """Create a new prompt fragment."""
    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()

            conn.execute("""
                INSERT INTO prompt_fragments
                (name, category, content, description, priority, enabled, created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """, (name, category, content, description, priority, now, now, created_by))

            conn.commit()
            conn.close()

            log_with_context(logger, "info", "Fragment created",
                           name=name, category=category, created_by=created_by)
            return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to create fragment", error=str(e))
            return False


def get_fragment_history(name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get change history for a fragment."""
    try:
        conn = _get_conn()
        cursor = conn.execute("""
            SELECT * FROM prompt_history
            WHERE fragment_name = ?
            ORDER BY changed_at DESC
            LIMIT ?
        """, (name, limit))
        history = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return history
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get history", error=str(e))
        return []


def get_fragments_summary() -> Dict[str, Any]:
    """Get summary of all prompt fragments."""
    try:
        conn = _get_conn()

        cursor = conn.execute("SELECT COUNT(*) as total FROM prompt_fragments")
        total = cursor.fetchone()["total"]

        cursor = conn.execute("SELECT COUNT(*) as cnt FROM prompt_fragments WHERE enabled = 1")
        enabled = cursor.fetchone()["cnt"]

        cursor = conn.execute("""
            SELECT category, COUNT(*) as cnt
            FROM prompt_fragments
            GROUP BY category
        """)
        by_category = {row["category"]: row["cnt"] for row in cursor.fetchall()}

        cursor = conn.execute("SELECT COUNT(*) as cnt FROM prompt_history")
        history_count = cursor.fetchone()["cnt"]

        conn.close()

        return {
            "total_fragments": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "by_category": by_category,
            "total_changes": history_count
        }
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get summary", error=str(e))
        return {"error": str(e)}
