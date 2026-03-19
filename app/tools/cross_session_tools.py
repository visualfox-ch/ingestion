"""
Cross-Session Continuity Tools - Tier 3 #11

Tools for managing session continuity:
- get_session_context: Restore context from previous sessions
- create_thread: Start a new conversation thread
- update_thread: Update thread status/summary
- create_handoff: Leave a note for the next session
- get_session_stats: View session statistics
"""

from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger, log_with_context

logger = get_logger("jarvis.tools.cross_session")


def _log(level: str, msg: str, **kwargs):
    """Helper to log with context."""
    log_with_context(logger, level, msg, **kwargs)

# Thread pool for async-to-sync conversion
_executor = ThreadPoolExecutor(max_workers=2)


def get_cross_session_tools() -> List[Dict[str, Any]]:
    """Return cross-session continuity tool definitions."""
    return [
        {
            "name": "get_session_context",
            "description": (
                "Holt den Kontext aus vorherigen Sessions: letzte Themen, "
                "offene Threads, ausstehende Handoffs. Nutze dies zu Session-Beginn."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "include_recap": {
                        "type": "boolean",
                        "description": "Zusammenfassung für User generieren (default: true)"
                    },
                    "specialist": {
                        "type": "string",
                        "description": "Spezifischer Specialist-Kontext laden"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["session", "context", "kontext", "history", "continue"]
            ).__dict__
        },
        {
            "name": "create_conversation_thread",
            "description": (
                "Erstellt einen neuen Gesprächs-Thread für ein Thema das "
                "über mehrere Sessions verfolgt werden soll. Z.B. 'Fitness-Ziel: 5kg abnehmen'."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Thema des Threads"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["fitness", "work", "personal", "health", "finance", "learning", "other"],
                        "description": "Kategorie des Threads"
                    },
                    "specialist": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Zuständiger Specialist (optional)"
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priorität 1-100 (default: 50)"
                    }
                },
                "required": ["topic", "category"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["thread", "topic", "thema", "verfolgen", "track"]
            ).__dict__
        },
        {
            "name": "update_conversation_thread",
            "description": (
                "Aktualisiert einen Gesprächs-Thread: Status ändern, "
                "Zusammenfassung aktualisieren, Priorität anpassen."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {
                        "type": "string",
                        "description": "ID des Threads"
                    },
                    "context_summary": {
                        "type": "string",
                        "description": "Aktuelle Zusammenfassung des Themas"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "resolved", "archived"],
                        "description": "Neuer Status"
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Neue Priorität 1-100"
                    }
                },
                "required": ["thread_id"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["thread", "update", "status", "resolve"]
            ).__dict__
        },
        {
            "name": "create_session_handoff",
            "description": (
                "Erstellt einen Handoff für die nächste Session: Erinnerung, "
                "Follow-up, oder Kontext-Übergabe an einen Specialist."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Kurzer Titel des Handoffs"
                    },
                    "content": {
                        "type": "string",
                        "description": "Inhalt/Details des Handoffs"
                    },
                    "handoff_type": {
                        "type": "string",
                        "enum": ["context", "reminder", "follow_up", "escalation"],
                        "description": "Art des Handoffs"
                    },
                    "for_specialist": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Ziel-Specialist (optional)"
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priorität 1-100 (default: 50)"
                    },
                    "expires_hours": {
                        "type": "integer",
                        "description": "Gültigkeit in Stunden (optional)"
                    }
                },
                "required": ["title", "content"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["handoff", "reminder", "erinnerung", "follow-up", "next"]
            ).__dict__
        },
        {
            "name": "list_active_threads",
            "description": (
                "Zeigt alle aktiven Gesprächs-Threads eines Users. "
                "Hilft beim Überblick über laufende Themen."
            ),
            "category": ToolCategory.MONITORING.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter nach Kategorie"
                    },
                    "specialist": {
                        "type": "string",
                        "description": "Filter nach Specialist"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.MONITORING,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["threads", "topics", "themen", "active", "list"]
            ).__dict__
        },
        {
            "name": "get_session_stats",
            "description": (
                "Zeigt Session-Statistiken: Anzahl Sessions, Dauer, "
                "häufigste Specialists, aktive Threads."
            ),
            "category": ToolCategory.MONITORING.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Zeitraum in Tagen (default: 30)"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.MONITORING,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["stats", "statistics", "sessions", "usage"]
            ).__dict__
        }
    ]


async def execute_cross_session_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    user_id: str = "1",
    session_id: str = None
) -> Dict[str, Any]:
    """Execute a cross-session tool."""
    try:
        from app.services.cross_session_service import get_cross_session_service

        service = get_cross_session_service()

        if tool_name == "get_session_context":
            include_recap = arguments.get("include_recap", True)
            specialist = arguments.get("specialist")

            context = service.restore_session_context(
                user_id=user_id,
                session_id=session_id or "unknown",
                specialist=specialist
            )

            result = {
                "success": True,
                "last_session": {
                    "summary": context.last_session_summary,
                    "topics": context.last_session_topics,
                    "ended_at": context.last_session_ended.isoformat() if context.last_session_ended else None
                },
                "active_threads": context.active_threads,
                "pending_handoffs": context.pending_handoffs,
                "specialist_memories": context.specialist_memories
            }

            if include_recap:
                recap = service.build_session_recap(context)
                if recap:
                    result["recap"] = recap

            return result

        elif tool_name == "create_conversation_thread":
            thread_id = service.create_thread(
                user_id=user_id,
                topic=arguments["topic"],
                category=arguments["category"],
                session_id=session_id or "unknown",
                specialist=arguments.get("specialist"),
                priority=arguments.get("priority", 50)
            )

            if thread_id:
                return {
                    "success": True,
                    "thread_id": thread_id,
                    "topic": arguments["topic"],
                    "message": f"Thread '{arguments['topic']}' erstellt"
                }
            else:
                return {"success": False, "error": "Thread creation failed"}

        elif tool_name == "update_conversation_thread":
            success = service.update_thread(
                thread_id=arguments["thread_id"],
                session_id=session_id or "unknown",
                context_summary=arguments.get("context_summary"),
                status=arguments.get("status"),
                priority=arguments.get("priority")
            )

            return {
                "success": success,
                "thread_id": arguments["thread_id"],
                "updated": arguments.get("status") or "context"
            }

        elif tool_name == "create_session_handoff":
            handoff_id = service.create_handoff(
                user_id=user_id,
                session_id=session_id or "unknown",
                title=arguments["title"],
                content=arguments["content"],
                handoff_type=arguments.get("handoff_type", "context"),
                priority=arguments.get("priority", 50),
                for_specialist=arguments.get("for_specialist"),
                expires_hours=arguments.get("expires_hours")
            )

            if handoff_id:
                return {
                    "success": True,
                    "handoff_id": handoff_id,
                    "title": arguments["title"],
                    "message": f"Handoff '{arguments['title']}' für nächste Session erstellt"
                }
            else:
                return {"success": False, "error": "Handoff creation failed"}

        elif tool_name == "list_active_threads":
            from app.postgres_state import get_conn

            with get_conn() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT thread_id, topic, category, specialist,
                               context_summary, priority, last_active_at,
                               session_count
                        FROM jarvis_conversation_threads
                        WHERE user_id = %s AND status = 'active'
                    """
                    params = [user_id]

                    if arguments.get("category"):
                        query += " AND category = %s"
                        params.append(arguments["category"])

                    if arguments.get("specialist"):
                        query += " AND specialist = %s"
                        params.append(arguments["specialist"])

                    query += " ORDER BY priority DESC, last_active_at DESC"

                    cur.execute(query, params)

                    threads = [
                        {
                            "thread_id": row["thread_id"],
                            "topic": row["topic"],
                            "category": row["category"],
                            "specialist": row["specialist"],
                            "summary": row["context_summary"],
                            "priority": row["priority"],
                            "sessions": row["session_count"],
                            "last_active": row["last_active_at"].isoformat() if row["last_active_at"] else None
                        }
                        for row in cur.fetchall()
                    ]

                    return {
                        "success": True,
                        "threads": threads,
                        "count": len(threads)
                    }

        elif tool_name == "get_session_stats":
            days = arguments.get("days", 30)
            stats = service.get_session_stats(user_id, days)
            return {"success": True, **stats}

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        _log("error", f"Cross-session tool error: {e}")
        return {"success": False, "error": str(e)}


CROSS_SESSION_TOOLS = {
    "get_session_context",
    "create_conversation_thread",
    "update_conversation_thread",
    "create_session_handoff",
    "list_active_threads",
    "get_session_stats"
}


def is_cross_session_tool(tool_name: str) -> bool:
    """Check if a tool name is a cross-session tool."""
    return tool_name in CROSS_SESSION_TOOLS
