"""
Learning & Memory Tools (T006 Refactor)

Tools for cross-session learning and context persistence:
- record_learning, get_learnings: Learning/insight storage
- store_context, recall_context, forget_context: Context persistence
- record_learnings_batch, store_contexts_batch: Batch operations
"""

from typing import Dict, Any
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger("jarvis.tools.learning_memory")

# Import shared utilities from parent
try:
    from ..logging_utils import log_with_context
    from .. import metrics
except ImportError:
    # Fallback for direct execution
    def log_with_context(logger, level, msg, **kwargs):
        getattr(logger, level)(f"{msg} {kwargs}")
    class metrics:
        @staticmethod
        def inc(name): pass


# ============ Tool Definitions ============

LEARNING_MEMORY_TOOLS = [
    # Learning Tools
    {
        "name": "record_learning",
        "description": "Record a learning, insight, or pattern for cross-session analysis. Use when you discover something important about the user, workflow, or system.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The learning or insight to record"
                },
                "category": {
                    "type": "string",
                    "description": "Category: general, capability, preference, workflow, technical",
                    "enum": ["general", "capability", "preference", "workflow", "technical"],
                    "default": "general"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level 0.0-1.0",
                    "default": 0.8
                },
                "source": {
                    "type": "string",
                    "description": "Source: conversation, observation, feedback",
                    "default": "conversation"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for the learning"
                }
            },
            "required": ["fact"]
        }
    },
    {
        "name": "get_learnings",
        "description": "Retrieve recorded learnings and insights. Returns a summary grouped by category. Use to recall what you've learned across sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                    "enum": ["general", "capability", "preference", "workflow", "technical"]
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search",
                    "default": 30
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results",
                    "default": 10
                },
                "compact": {
                    "type": "boolean",
                    "description": "Return compact format with summary (default true)",
                    "default": True
                }
            }
        }
    },
    # Context Persistence Tools
    {
        "name": "store_context",
        "description": "Store a context value for later retrieval. Use for cross-session state, preferences, or temporary memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Unique key for this context"
                },
                "value": {
                    "type": "string",
                    "description": "Value to store (string or JSON)"
                },
                "context_type": {
                    "type": "string",
                    "description": "Type: general, preference, state, memory",
                    "enum": ["general", "preference", "state", "memory"],
                    "default": "general"
                },
                "ttl_hours": {
                    "type": "integer",
                    "description": "Time to live in hours (default 168 = 1 week)",
                    "default": 168
                }
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "recall_context",
        "description": "Recall a stored context value. Use to retrieve cross-session state or memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key to recall (if omitted, returns all for context_type)"
                },
                "context_type": {
                    "type": "string",
                    "description": "Filter by type",
                    "enum": ["general", "preference", "state", "memory"]
                }
            }
        }
    },
    {
        "name": "forget_context",
        "description": "Delete stored context. Use to clean up old or invalid context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Specific key to delete"
                },
                "context_type": {
                    "type": "string",
                    "description": "Delete all of this type"
                }
            }
        }
    },
    # Batch Operations
    {
        "name": "record_learnings_batch",
        "description": "Record MULTIPLE learnings in ONE call. Use this instead of calling record_learning multiple times to avoid hitting step limits! Each item needs 'fact' (required), optionally 'category', 'confidence', 'source', 'context'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learnings": {
                    "type": "array",
                    "description": "Array of learning objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "The learning/insight to record"},
                            "category": {"type": "string", "description": "Category: general, technical, preference, workflow, capability"},
                            "confidence": {"type": "number", "description": "Confidence 0.0-1.0"},
                            "source": {"type": "string", "description": "Source: conversation, observation, user"},
                            "context": {"type": "string", "description": "Additional context"}
                        },
                        "required": ["fact"]
                    }
                }
            },
            "required": ["learnings"]
        }
    },
    {
        "name": "store_contexts_batch",
        "description": "Store MULTIPLE context values in ONE call. Use this instead of calling store_context multiple times to avoid hitting step limits! Each item needs 'key' and 'value' (required), optionally 'context_type', 'ttl_hours'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contexts": {
                    "type": "array",
                    "description": "Array of context objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Unique key for this context"},
                            "value": {"description": "Value to store (string or object)"},
                            "context_type": {"type": "string", "description": "Type: general, preference, state, memory"},
                            "ttl_hours": {"type": "integer", "description": "Time to live in hours (default 168 = 1 week)"}
                        },
                        "required": ["key", "value"]
                    }
                }
            },
            "required": ["contexts"]
        }
    },
]


# ============ Learning Tools Implementation ============

def tool_record_learning(
    fact: str = None,
    category: str = "general",
    confidence: float = 0.8,
    source: str = "conversation",
    context: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record a learning/insight for cross-session pattern analysis.

    Args:
        fact: The learning or insight to record
        category: Category (general, capability, preference, workflow, technical)
        confidence: Confidence level 0.0-1.0
        source: Source of learning (conversation, observation, feedback)
        context: Additional context

    Returns:
        Status of recording
    """
    log_with_context(logger, "info", "Tool: record_learning", category=category)
    metrics.inc("tool_record_learning")

    if not fact:
        return {"error": "fact is required"}

    try:
        from .. import session_manager

        conn = session_manager._get_conn()

        # Create learnings table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT 'conversation',
                context TEXT,
                created_at TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                migration_candidate INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learnings_category ON jarvis_learnings(category)")

        # Insert learning
        now = datetime.utcnow().isoformat() + "Z"
        cursor = conn.execute("""
            INSERT INTO jarvis_learnings (fact, category, confidence, source, context, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fact, category, confidence, source, context, now))

        conn.commit()
        learning_id = cursor.lastrowid
        conn.close()

        return {
            "status": "recorded",
            "learning_id": learning_id,
            "fact": fact[:100] + "..." if len(fact) > 100 else fact,
            "category": category,
            "confidence": confidence
        }

    except Exception as e:
        log_with_context(logger, "error", "record_learning failed", error=str(e))
        return {"error": str(e)}


def tool_get_learnings(
    category: str = None,
    days_back: int = 30,
    limit: int = 20,
    compact: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Retrieve recorded learnings/insights.

    Args:
        category: Filter by category
        days_back: How many days back to search
        limit: Maximum results
        compact: If True, return only essential fields (fact, category)

    Returns:
        List of learnings with summary
    """
    log_with_context(logger, "info", "Tool: get_learnings", category=category, limit=limit)
    metrics.inc("tool_get_learnings")

    try:
        from .. import session_manager

        conn = session_manager._get_conn()

        cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat() + "Z"

        if category:
            rows = conn.execute("""
                SELECT id, fact, category, confidence, source, created_at FROM jarvis_learnings
                WHERE category = ? AND created_at >= ?
                ORDER BY confidence DESC, created_at DESC LIMIT ?
            """, (category, cutoff, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, fact, category, confidence, source, created_at FROM jarvis_learnings
                WHERE created_at >= ?
                ORDER BY confidence DESC, created_at DESC LIMIT ?
            """, (cutoff, limit)).fetchall()

        conn.close()

        # Build compact or full learnings list
        if compact:
            learnings = []
            by_category = {}
            for row in rows:
                cat = row['category'] or 'general'
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(row['fact'])
                learnings.append({
                    "fact": row['fact'],
                    "category": cat,
                    "confidence": row['confidence']
                })

            # Build human-readable summary
            summary_parts = []
            for cat, facts in by_category.items():
                summary_parts.append(f"**{cat.title()}** ({len(facts)}): " + "; ".join(facts[:3]))
                if len(facts) > 3:
                    summary_parts[-1] += f" (+{len(facts)-3} more)"

            return {
                "summary": "\n".join(summary_parts),
                "learnings": learnings,
                "count": len(learnings),
                "by_category": {k: len(v) for k, v in by_category.items()},
                "days_searched": days_back
            }
        else:
            learnings = [dict(row) for row in rows]
            return {
                "learnings": learnings,
                "count": len(learnings),
                "category_filter": category,
                "days_searched": days_back
            }

    except Exception as e:
        # Table might not exist yet
        if "no such table" in str(e):
            return {"learnings": [], "count": 0, "note": "No learnings recorded yet"}
        log_with_context(logger, "error", "get_learnings failed", error=str(e))
        return {"error": str(e)}


# ============ Context Persistence Tools Implementation ============

def tool_store_context(
    key: str = None,
    value: str = None,
    context_type: str = "general",
    ttl_hours: int = 168,  # 1 week default
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Store a context value for later retrieval.

    Args:
        key: Unique key for this context
        value: Value to store (string, will be JSON serialized if dict)
        context_type: Type of context (general, preference, state, memory)
        ttl_hours: Time to live in hours (default 168 = 1 week)
        user_id: Optional user ID

    Returns:
        Status of storage
    """
    log_with_context(logger, "info", "Tool: store_context", key=key, context_type=context_type)
    metrics.inc("tool_store_context")

    if not key or value is None:
        return {"error": "key and value are required"}

    try:
        from .. import session_manager

        conn = session_manager._get_conn()

        # Create context_store table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                context_type TEXT DEFAULT 'general',
                user_id INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                UNIQUE(key, user_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_key ON context_store(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_type ON context_store(context_type)")

        now = datetime.utcnow()
        expires = (now + timedelta(hours=ttl_hours)).isoformat() + "Z"
        now_str = now.isoformat() + "Z"

        # Serialize value if needed
        if isinstance(value, (dict, list)):
            value = json.dumps(value)

        # Upsert
        conn.execute("""
            INSERT INTO context_store (key, value, context_type, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key, user_id) DO UPDATE SET
                value = excluded.value,
                context_type = excluded.context_type,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
        """, (key, value, context_type, user_id, now_str, expires))

        conn.commit()
        conn.close()

        return {
            "status": "stored",
            "key": key,
            "context_type": context_type,
            "expires_at": expires
        }

    except Exception as e:
        log_with_context(logger, "error", "store_context failed", error=str(e))
        return {"error": str(e)}


def tool_recall_context(
    key: str = None,
    context_type: str = None,
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall a stored context value.

    Args:
        key: Key to recall (if None, returns all for context_type)
        context_type: Filter by type
        user_id: Optional user ID filter

    Returns:
        Stored context value(s)
    """
    log_with_context(logger, "info", "Tool: recall_context", key=key, context_type=context_type)
    metrics.inc("tool_recall_context")

    try:
        from .. import session_manager

        conn = session_manager._get_conn()
        now = datetime.utcnow().isoformat() + "Z"

        if key:
            # Get specific key
            row = conn.execute("""
                SELECT * FROM context_store
                WHERE key = ? AND (user_id = ? OR user_id IS NULL)
                AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC LIMIT 1
            """, (key, user_id, now)).fetchone()

            conn.close()

            if not row:
                return {"found": False, "key": key}

            value = row["value"]
            # Try to deserialize JSON
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass

            return {
                "found": True,
                "key": key,
                "value": value,
                "context_type": row["context_type"],
                "created_at": row["created_at"]
            }
        else:
            # Get all for context_type
            if context_type:
                rows = conn.execute("""
                    SELECT * FROM context_store
                    WHERE context_type = ? AND (user_id = ? OR user_id IS NULL)
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC LIMIT 50
                """, (context_type, user_id, now)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM context_store
                    WHERE (user_id = ? OR user_id IS NULL)
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC LIMIT 50
                """, (user_id, now)).fetchall()

            conn.close()

            contexts = []
            for row in rows:
                value = row["value"]
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
                contexts.append({
                    "key": row["key"],
                    "value": value,
                    "context_type": row["context_type"],
                    "created_at": row["created_at"]
                })

            return {
                "found": len(contexts) > 0,
                "contexts": contexts,
                "count": len(contexts)
            }

    except Exception as e:
        if "no such table" in str(e):
            return {"found": False, "note": "No context stored yet"}
        log_with_context(logger, "error", "recall_context failed", error=str(e))
        return {"error": str(e)}


def tool_forget_context(
    key: str = None,
    context_type: str = None,
    user_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Delete stored context.

    Args:
        key: Specific key to delete
        context_type: Delete all of this type
        user_id: User ID filter

    Returns:
        Deletion status
    """
    log_with_context(logger, "info", "Tool: forget_context", key=key, context_type=context_type)
    metrics.inc("tool_forget_context")

    if not key and not context_type:
        return {"error": "Either key or context_type is required"}

    try:
        from .. import session_manager

        conn = session_manager._get_conn()

        if key:
            cursor = conn.execute("""
                DELETE FROM context_store WHERE key = ? AND (user_id = ? OR user_id IS NULL)
            """, (key, user_id))
        else:
            cursor = conn.execute("""
                DELETE FROM context_store WHERE context_type = ? AND (user_id = ? OR user_id IS NULL)
            """, (context_type, user_id))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return {
            "status": "deleted",
            "deleted_count": deleted,
            "key": key,
            "context_type": context_type
        }

    except Exception as e:
        if "no such table" in str(e):
            return {"status": "ok", "deleted_count": 0}
        log_with_context(logger, "error", "forget_context failed", error=str(e))
        return {"error": str(e)}


# ============ Batch Operations Implementation ============

def tool_record_learnings_batch(
    learnings: list = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record multiple learnings in a single operation.

    Use this instead of calling record_learning multiple times to avoid step limits!

    Args:
        learnings: List of dicts, each with: fact (required), category, confidence, source, context
                   Example: [{"fact": "...", "category": "technical"}, {"fact": "...", "confidence": 0.9}]

    Returns:
        Summary of all recorded learnings
    """
    log_with_context(logger, "info", "Tool: record_learnings_batch", count=len(learnings) if learnings else 0)
    metrics.inc("tool_record_learnings_batch")

    if not learnings or not isinstance(learnings, list):
        return {"error": "learnings must be a non-empty list"}

    try:
        from .. import session_manager

        conn = session_manager._get_conn()

        # Create table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT 'conversation',
                context TEXT,
                created_at TEXT NOT NULL,
                validated INTEGER DEFAULT 0,
                migration_candidate INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learnings_category ON jarvis_learnings(category)")

        results = []
        now = datetime.utcnow().isoformat() + "Z"

        for item in learnings:
            if not isinstance(item, dict) or "fact" not in item:
                results.append({"error": "Invalid item, requires 'fact'"})
                continue

            fact = item["fact"]
            category = item.get("category", "general")
            confidence = item.get("confidence", 0.8)
            source = item.get("source", "batch")
            context = item.get("context")

            cursor = conn.execute("""
                INSERT INTO jarvis_learnings (fact, category, confidence, source, context, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fact, category, confidence, source, context, now))

            results.append({
                "learning_id": cursor.lastrowid,
                "fact": fact[:50] + "..." if len(fact) > 50 else fact,
                "category": category
            })

        conn.commit()
        conn.close()

        return {
            "status": "batch_recorded",
            "total_count": len(results),
            "success_count": sum(1 for r in results if "learning_id" in r),
            "results": results
        }

    except Exception as e:
        log_with_context(logger, "error", "record_learnings_batch failed", error=str(e))
        return {"error": str(e)}


def tool_store_contexts_batch(
    contexts: list = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Store multiple context values in a single operation.

    Use this instead of calling store_context multiple times to avoid step limits!

    Args:
        contexts: List of dicts, each with: key (required), value (required), context_type, ttl_hours
                  Example: [{"key": "k1", "value": "v1"}, {"key": "k2", "value": {"nested": true}}]

    Returns:
        Summary of all stored contexts
    """
    log_with_context(logger, "info", "Tool: store_contexts_batch", count=len(contexts) if contexts else 0)
    metrics.inc("tool_store_contexts_batch")

    if not contexts or not isinstance(contexts, list):
        return {"error": "contexts must be a non-empty list"}

    try:
        from .. import session_manager

        conn = session_manager._get_conn()

        # Create table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                context_type TEXT DEFAULT 'general',
                user_id INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                UNIQUE(key, user_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_key ON context_store(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_context_type ON context_store(context_type)")

        results = []
        now = datetime.utcnow()
        now_str = now.isoformat() + "Z"
        user_id = kwargs.get("user_id")

        for item in contexts:
            if not isinstance(item, dict) or "key" not in item or "value" not in item:
                results.append({"error": "Invalid item, requires 'key' and 'value'"})
                continue

            key = item["key"]
            value = item["value"]
            context_type = item.get("context_type", "general")
            ttl_hours = item.get("ttl_hours", 168)

            # Serialize value if needed
            if isinstance(value, (dict, list)):
                value = json.dumps(value)

            expires = (now + timedelta(hours=ttl_hours)).isoformat() + "Z"

            conn.execute("""
                INSERT INTO context_store (key, value, context_type, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, user_id) DO UPDATE SET
                    value = excluded.value,
                    context_type = excluded.context_type,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
            """, (key, value, context_type, user_id, now_str, expires))

            results.append({
                "key": key,
                "context_type": context_type,
                "expires_at": expires
            })

        conn.commit()
        conn.close()

        return {
            "status": "batch_stored",
            "total_count": len(results),
            "success_count": sum(1 for r in results if "key" in r),
            "results": results
        }

    except Exception as e:
        log_with_context(logger, "error", "store_contexts_batch failed", error=str(e))
        return {"error": str(e)}
