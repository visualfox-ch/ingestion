"""
Handoff Tools - U4: AI Assistant Coordination

Tools for Jarvis to coordinate with external AI assistants:
- Claude Code, Copilot, Codex

Enables:
- Task handoff to appropriate assistant
- Context sharing between assistants
- Handoff status tracking
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import json

logger = logging.getLogger(__name__)


def create_handoff(
    to_assistant: str,
    task_description: str,
    context: str = "",
    files: List[str] = None,
    priority: str = "normal",
    expected_outcome: str = ""
) -> Dict[str, Any]:
    """
    Create a task handoff to an external AI assistant.

    Args:
        to_assistant: Target assistant (claude_code, copilot, codex)
        task_description: What needs to be done
        context: Relevant context for the task
        files: List of relevant file paths
        priority: low, normal, high, urgent
        expected_outcome: What success looks like

    Returns:
        Handoff ID and status
    """
    try:
        from app.services.agent_message_service import get_agent_message_service

        service = get_agent_message_service()

        # Validate assistant
        valid_assistants = ["claude_code", "copilot", "codex"]
        if to_assistant not in valid_assistants:
            return {
                "success": False,
                "error": f"Unknown assistant: {to_assistant}. Valid: {valid_assistants}"
            }

        content = {
            "intent": "delegate_task",
            "payload": {
                "task": task_description,
                "context": context,
                "files": files or [],
                "expected_outcome": expected_outcome,
                "created_by": "jarvis"
            },
            "expected_response": "required"
        }

        result = service.send_message(
            from_agent="jarvis",
            to_agent=to_assistant,
            message_type="handoff",
            subject=f"Task: {task_description[:50]}...",
            content=content,
            priority=priority
        )

        if result.get("success"):
            return {
                "success": True,
                "handoff_id": result["message_id"],
                "to": to_assistant,
                "task": task_description[:100],
                "status": "pending",
                "message": f"Handoff an {to_assistant} erstellt. ID: {result['message_id']}"
            }

        return result

    except Exception as e:
        logger.error(f"Create handoff failed: {e}")
        return {"success": False, "error": str(e)}


def get_pending_handoffs(
    assistant: str = None,
    include_completed: bool = False
) -> Dict[str, Any]:
    """
    Get pending handoffs for an assistant.

    Args:
        assistant: Filter by assistant (or all if None)
        include_completed: Include completed handoffs

    Returns:
        List of pending handoffs
    """
    try:
        from app.services.agent_message_service import get_agent_message_service

        service = get_agent_message_service()

        # Get messages for the assistant
        if assistant:
            result = service.get_messages(
                agent=assistant,
                message_type="handoff",
                status=None if include_completed else "pending",
                limit=20
            )
        else:
            # Get all handoffs from jarvis
            from app.postgres_state import get_dict_cursor
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT message_id, to_agent, subject, content, priority, status, created_at
                    FROM jarvis_agent_messages
                    WHERE from_agent = 'jarvis'
                      AND message_type = 'handoff'
                      AND to_agent IN ('claude_code', 'copilot', 'codex')
                    ORDER BY created_at DESC
                    LIMIT 20
                """)

                handoffs = []
                for row in cur.fetchall():
                    handoffs.append({
                        "handoff_id": row["message_id"],
                        "to": row["to_agent"],
                        "subject": row["subject"],
                        "priority": row["priority"],
                        "status": row["status"],
                        "created": row["created_at"].isoformat() if row["created_at"] else None
                    })

                return {
                    "success": True,
                    "handoffs": handoffs,
                    "count": len(handoffs)
                }

        return result

    except Exception as e:
        logger.error(f"Get pending handoffs failed: {e}")
        return {"success": False, "error": str(e)}


def complete_handoff(
    handoff_id: str,
    outcome: str,
    result_summary: str = "",
    files_modified: List[str] = None
) -> Dict[str, Any]:
    """
    Mark a handoff as completed.

    Args:
        handoff_id: The handoff message ID
        outcome: success, partial, failed
        result_summary: Summary of what was done
        files_modified: List of files that were changed

    Returns:
        Completion status
    """
    try:
        from app.services.agent_message_service import get_agent_message_service
        from app.postgres_state import get_cursor

        service = get_agent_message_service()

        # Update the handoff status
        with get_cursor() as cur:
            cur.execute("""
                UPDATE jarvis_agent_messages
                SET status = 'processed',
                    processed_at = NOW(),
                    metadata = metadata || %s
                WHERE message_id = %s
                RETURNING to_agent, subject
            """, (
                json.dumps({
                    "outcome": outcome,
                    "result_summary": result_summary,
                    "files_modified": files_modified or [],
                    "completed_at": datetime.now().isoformat()
                }),
                handoff_id
            ))

            row = cur.fetchone()
            if not row:
                return {"success": False, "error": "Handoff not found"}

        return {
            "success": True,
            "handoff_id": handoff_id,
            "outcome": outcome,
            "message": f"Handoff {handoff_id} als {outcome} markiert"
        }

    except Exception as e:
        logger.error(f"Complete handoff failed: {e}")
        return {"success": False, "error": str(e)}


def get_handoff_context(
    handoff_id: str
) -> Dict[str, Any]:
    """
    Get full context for a handoff.

    Args:
        handoff_id: The handoff message ID

    Returns:
        Full handoff details including context
    """
    try:
        from app.postgres_state import get_dict_cursor

        with get_dict_cursor() as cur:
            cur.execute("""
                SELECT message_id, from_agent, to_agent, subject, content,
                       priority, status, metadata, created_at, processed_at
                FROM jarvis_agent_messages
                WHERE message_id = %s
            """, (handoff_id,))

            row = cur.fetchone()
            if not row:
                return {"success": False, "error": "Handoff not found"}

            content = row["content"] or {}
            payload = content.get("payload", {})

            return {
                "success": True,
                "handoff_id": row["message_id"],
                "from": row["from_agent"],
                "to": row["to_agent"],
                "subject": row["subject"],
                "task": payload.get("task", ""),
                "context": payload.get("context", ""),
                "files": payload.get("files", []),
                "expected_outcome": payload.get("expected_outcome", ""),
                "priority": row["priority"],
                "status": row["status"],
                "metadata": row["metadata"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }

    except Exception as e:
        logger.error(f"Get handoff context failed: {e}")
        return {"success": False, "error": str(e)}


def suggest_assistant(
    task_type: str,
    complexity: str = "medium"
) -> Dict[str, Any]:
    """
    Suggest the best assistant for a task type.

    Args:
        task_type: Type of task (code_review, refactoring, new_feature, debugging, docs)
        complexity: low, medium, high

    Returns:
        Recommended assistant with reasoning
    """
    # Simple heuristic-based routing
    recommendations = {
        "code_review": {
            "low": ("copilot", "Quick inline suggestions"),
            "medium": ("claude_code", "Comprehensive review with context"),
            "high": ("claude_code", "Deep analysis needed")
        },
        "refactoring": {
            "low": ("copilot", "Simple transformations"),
            "medium": ("claude_code", "Multi-file refactoring"),
            "high": ("claude_code", "Architectural changes")
        },
        "new_feature": {
            "low": ("copilot", "Small additions"),
            "medium": ("claude_code", "Feature implementation"),
            "high": ("claude_code", "Complex feature design")
        },
        "debugging": {
            "low": ("copilot", "Quick fixes"),
            "medium": ("claude_code", "Investigation needed"),
            "high": ("claude_code", "Deep debugging")
        },
        "docs": {
            "low": ("copilot", "Inline comments"),
            "medium": ("claude_code", "Documentation writing"),
            "high": ("claude_code", "Technical documentation")
        }
    }

    task_recs = recommendations.get(task_type, {})
    rec = task_recs.get(complexity, ("claude_code", "Default recommendation"))

    return {
        "success": True,
        "recommended_assistant": rec[0],
        "reason": rec[1],
        "task_type": task_type,
        "complexity": complexity,
        "alternatives": ["claude_code", "copilot", "codex"]
    }


# Tool definitions for registration
HANDOFF_TOOLS = [
    {
        "name": "create_handoff",
        "description": "Create a task handoff to an external AI assistant (Claude Code, Copilot, Codex). Use when a coding task should be delegated.",
        "function": create_handoff,
        "parameters": {
            "type": "object",
            "properties": {
                "to_assistant": {
                    "type": "string",
                    "enum": ["claude_code", "copilot", "codex"],
                    "description": "Target AI assistant"
                },
                "task_description": {
                    "type": "string",
                    "description": "Clear description of what needs to be done"
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context (recent changes, related issues)"
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant file paths"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                    "default": "normal"
                },
                "expected_outcome": {
                    "type": "string",
                    "description": "What success looks like"
                }
            },
            "required": ["to_assistant", "task_description"]
        }
    },
    {
        "name": "get_pending_handoffs",
        "description": "Get pending task handoffs for AI assistants. Shows what tasks are waiting.",
        "function": get_pending_handoffs,
        "parameters": {
            "type": "object",
            "properties": {
                "assistant": {
                    "type": "string",
                    "enum": ["claude_code", "copilot", "codex"],
                    "description": "Filter by assistant (optional)"
                },
                "include_completed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include completed handoffs"
                }
            }
        }
    },
    {
        "name": "complete_handoff",
        "description": "Mark a handoff as completed after the task is done.",
        "function": complete_handoff,
        "parameters": {
            "type": "object",
            "properties": {
                "handoff_id": {
                    "type": "string",
                    "description": "The handoff message ID"
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": "Task outcome"
                },
                "result_summary": {
                    "type": "string",
                    "description": "Summary of what was done"
                },
                "files_modified": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files that were changed"
                }
            },
            "required": ["handoff_id", "outcome"]
        }
    },
    {
        "name": "get_handoff_context",
        "description": "Get full context for a specific handoff including task details and files.",
        "function": get_handoff_context,
        "parameters": {
            "type": "object",
            "properties": {
                "handoff_id": {
                    "type": "string",
                    "description": "The handoff message ID"
                }
            },
            "required": ["handoff_id"]
        }
    },
    {
        "name": "suggest_assistant",
        "description": "Get a recommendation for which AI assistant to use for a task type.",
        "function": suggest_assistant,
        "parameters": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "enum": ["code_review", "refactoring", "new_feature", "debugging", "docs"],
                    "description": "Type of coding task"
                },
                "complexity": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium"
                }
            },
            "required": ["task_type"]
        }
    }
]


def get_handoff_tools() -> list:
    """Return all handoff tool definitions."""
    return HANDOFF_TOOLS
