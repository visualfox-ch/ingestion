"""
Goal Management Tools - Tier 2 Feature

Provides Jarvis with tools to manage long-term goals:
- create_goal: Create a new goal with automatic decomposition
- get_active_goals: List all active goals
- get_goal_status: Get detailed status of a goal
- record_goal_progress: Record progress on a goal
- get_goal_reminders: Get proactive reminders for goals

These tools enable proactive goal tracking and support.
"""

from typing import Dict, Any, List, Optional

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger

logger = get_logger("jarvis.tools.goals")


def get_goal_tools() -> List[Dict[str, Any]]:
    """Return goal management tool definitions."""
    return [
        {
            "name": "create_goal",
            "description": (
                "Erstellt ein neues langfristiges Ziel mit automatischer Zerlegung in Milestones. "
                "Beispiel: 'Ich möchte 5kg in 12 Wochen abnehmen' -> Ziel mit Wochen-Milestones. "
                "Kategorien: fitness, health, work, learning, finance, relationship, habit, project"
            ),
            "category": ToolCategory.PROJECT.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel des Ziels (z.B. '5kg abnehmen')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optionale Beschreibung des Ziels"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["fitness", "health", "work", "learning", "finance", "relationship", "habit", "project", "other"],
                        "description": "Kategorie des Ziels"
                    },
                    "target_value": {
                        "type": "number",
                        "description": "Zielwert (z.B. 5 für 5kg)"
                    },
                    "target_unit": {
                        "type": "string",
                        "description": "Einheit (z.B. 'kg', 'Bücher', 'Stunden')"
                    },
                    "current_value": {
                        "type": "number",
                        "description": "Aktueller Wert (Startpunkt)"
                    },
                    "target_weeks": {
                        "type": "integer",
                        "description": "Anzahl Wochen bis zum Ziel"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optionale Tags"
                    }
                },
                "required": ["title", "category", "target_value", "target_unit", "target_weeks"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.PROJECT,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["ziel", "goal", "erstellen", "create", "milestone", "plan"]
            ).__dict__
        },
        {
            "name": "get_active_goals",
            "description": (
                "Zeigt alle aktiven Ziele mit ihrem aktuellen Status. "
                "Gibt eine Übersicht über Fortschritt und nächste Milestones."
            ),
            "category": ToolCategory.PROJECT.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["fitness", "health", "work", "learning", "finance", "relationship", "habit", "project", "other", "all"],
                        "description": "Optional: nur Ziele einer bestimmten Kategorie"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.PROJECT,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["ziele", "goals", "aktiv", "active", "status", "übersicht"]
            ).__dict__
        },
        {
            "name": "get_goal_status",
            "description": (
                "Gibt detaillierten Status eines Ziels: Fortschritt, Milestones, "
                "On-Track-Status und Empfehlungen."
            ),
            "category": ToolCategory.PROJECT.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "integer",
                        "description": "ID des Ziels"
                    }
                },
                "required": ["goal_id"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.PROJECT,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["ziel", "goal", "status", "fortschritt", "progress"]
            ).__dict__
        },
        {
            "name": "record_goal_progress",
            "description": (
                "Zeichnet Fortschritt für ein Ziel auf. Aktualisiert automatisch "
                "Milestone-Status und berechnet On-Track-Status."
            ),
            "category": ToolCategory.PROJECT.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "integer",
                        "description": "ID des Ziels"
                    },
                    "current_value": {
                        "type": "number",
                        "description": "Aktueller Wert (z.B. bereits abgenommene kg)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optionale Notizen zum Fortschritt"
                    }
                },
                "required": ["goal_id", "current_value"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.PROJECT,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["fortschritt", "progress", "update", "aktualisieren"]
            ).__dict__
        },
        {
            "name": "get_goal_reminders",
            "description": (
                "Gibt proaktive Erinnerungen für Ziele: überfällige Milestones, "
                "Behind-Schedule-Warnungen, anstehende Deadlines."
            ),
            "category": ToolCategory.PROJECT.value,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.PROJECT,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["erinnerung", "reminder", "deadline", "warnung", "proaktiv"]
            ).__dict__
        },
        {
            "name": "update_goal_status",
            "description": (
                "Ändert den Status eines Ziels: active, completed, paused, abandoned."
            ),
            "category": ToolCategory.PROJECT.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "integer",
                        "description": "ID des Ziels"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "completed", "paused", "abandoned"],
                        "description": "Neuer Status"
                    }
                },
                "required": ["goal_id", "status"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.PROJECT,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["status", "ändern", "complete", "pause", "abandon"]
            ).__dict__
        }
    ]


async def execute_goal_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    user_id: str = "micha"
) -> Dict[str, Any]:
    """Execute a goal management tool."""
    try:
        from app.services.goal_decomposition_service import (
            get_goal_service,
            GoalCategory,
            GoalStatus
        )

        service = get_goal_service()

        if tool_name == "create_goal":
            category = GoalCategory(arguments.get("category", "other"))
            goal = service.create_goal(
                user_id=user_id,
                title=arguments["title"],
                description=arguments.get("description", ""),
                category=category,
                target_value=arguments["target_value"],
                target_unit=arguments["target_unit"],
                current_value=arguments.get("current_value", 0),
                target_weeks=arguments["target_weeks"],
                tags=arguments.get("tags"),
                auto_decompose=True
            )

            # Format milestones for response
            milestones_summary = []
            for m in goal.milestones:
                milestones_summary.append({
                    "title": m.title,
                    "target": m.target_value,
                    "due": m.due_date.strftime("%d.%m.%Y") if m.due_date else None
                })

            return {
                "success": True,
                "goal_id": goal.id,
                "title": goal.title,
                "milestones_created": len(goal.milestones),
                "milestones": milestones_summary,
                "summary": (
                    f"Ziel '{goal.title}' erstellt mit {len(goal.milestones)} Milestones. "
                    f"Ziel: {goal.target_value} {goal.target_unit} in {arguments['target_weeks']} Wochen."
                )
            }

        elif tool_name == "get_active_goals":
            goals = service.get_active_goals(user_id)

            category_filter = arguments.get("category", "all")
            if category_filter != "all":
                goals = [g for g in goals if g.category.value == category_filter]

            goals_summary = []
            for g in goals:
                status = service.get_goal_status(g.id)
                goals_summary.append({
                    "id": g.id,
                    "title": g.title,
                    "category": g.category.value,
                    "progress": f"{status['progress']['percentage']:.0f}%" if status.get("success") else "?",
                    "on_track": status.get("on_track", False),
                    "days_remaining": status.get("timeline", {}).get("days_remaining"),
                    "current_milestone": status.get("milestones", {}).get("current", {}).get("title")
                })

            return {
                "success": True,
                "count": len(goals_summary),
                "goals": goals_summary,
                "summary": f"{len(goals_summary)} aktive Ziele gefunden."
            }

        elif tool_name == "get_goal_status":
            status = service.get_goal_status(arguments["goal_id"])
            return status

        elif tool_name == "record_goal_progress":
            result = service.record_progress(
                goal_id=arguments["goal_id"],
                current_value=arguments["current_value"],
                notes=arguments.get("notes", ""),
                source="jarvis_tool"
            )

            if result.get("success"):
                # Get updated status
                status = service.get_goal_status(arguments["goal_id"])
                result["updated_status"] = {
                    "progress": status.get("progress", {}),
                    "on_track": status.get("on_track"),
                    "recommendation": status.get("recommendation")
                }

            return result

        elif tool_name == "get_goal_reminders":
            reminders = service.get_proactive_reminders(user_id)

            if not reminders:
                return {
                    "success": True,
                    "count": 0,
                    "reminders": [],
                    "summary": "Keine Erinnerungen - alle Ziele sind auf Kurs!"
                }

            return {
                "success": True,
                "count": len(reminders),
                "reminders": reminders,
                "summary": f"{len(reminders)} Erinnerung(en) für deine Ziele."
            }

        elif tool_name == "update_goal_status":
            status = GoalStatus(arguments["status"])
            success = service.update_goal_status(arguments["goal_id"], status)

            return {
                "success": success,
                "goal_id": arguments["goal_id"],
                "new_status": status.value,
                "message": f"Ziel-Status auf '{status.value}' geändert." if success else "Fehler beim Ändern."
            }

        else:
            return {
                "success": False,
                "error": f"Unknown goal tool: {tool_name}"
            }

    except Exception as e:
        logger.error(f"Goal tool error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


# Tool category check for tool_executor
GOAL_TOOLS = {
    "create_goal",
    "get_active_goals",
    "get_goal_status",
    "record_goal_progress",
    "get_goal_reminders",
    "update_goal_status"
}


def is_goal_tool(tool_name: str) -> bool:
    """Check if a tool name is a goal tool."""
    return tool_name in GOAL_TOOLS
