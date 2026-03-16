"""
Context Engine Tools - Tier 3 #10

Tools for mood-aware context management:
- get_context: Get current context profile
- record_context_signal: Record a context signal
- get_context_rules: View active context rules
- get_context_stats: Get context engine statistics
"""

from typing import Dict, Any, List, Optional

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger

logger = get_logger("jarvis.tools.context")


def get_context_tools() -> List[Dict[str, Any]]:
    """Return context engine tool definitions."""
    return [
        {
            "name": "get_context",
            "description": (
                "Ermittelt den aktuellen Kontext: Stimmung, Energielevel, "
                "Stresslevel, Tageszeit. Nutze dies um deine Antworten "
                "an den Kontext anzupassen."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optionale Query für Emotion-Detection"
                    },
                    "rebuild": {
                        "type": "boolean",
                        "description": "Kontext neu aufbauen (default: false)"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["context", "mood", "stimmung", "energie", "stress"]
            ).__dict__
        },
        {
            "name": "record_context_signal",
            "description": (
                "Erfasst ein Kontext-Signal (z.B. Stimmung, Stress, Energie). "
                "Signale werden aggregiert um den Kontext zu verstehen."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "signal_type": {
                        "type": "string",
                        "enum": ["emotion", "stress", "energy", "focus", "activity"],
                        "description": "Art des Signals"
                    },
                    "signal_value": {
                        "type": "string",
                        "description": "Wert des Signals (z.B. 'stressed', 'energized')"
                    },
                    "intensity": {
                        "type": "number",
                        "description": "Intensität 0.0-1.0 (default: 0.5)"
                    },
                    "source": {
                        "type": "string",
                        "enum": ["user_input", "auto_detect", "calendar", "system"],
                        "description": "Quelle des Signals"
                    }
                },
                "required": ["signal_type", "signal_value"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["context", "signal", "record", "track"]
            ).__dict__
        },
        {
            "name": "get_context_rules",
            "description": (
                "Zeigt aktive Kontext-Regeln: Welche Bedingungen führen "
                "zu welchen Anpassungen (Ton, Verbosität, Tool-Prioritäten)."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "include_inactive": {
                        "type": "boolean",
                        "description": "Auch inaktive Regeln anzeigen"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["context", "rules", "regeln", "bedingungen"]
            ).__dict__
        },
        {
            "name": "get_context_stats",
            "description": (
                "Zeigt Context Engine Statistiken: häufigste Regeln, "
                "Signal-Verteilung, Effektivität."
            ),
            "category": ToolCategory.MONITORING.value,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.MONITORING,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["context", "stats", "analytics", "statistik"]
            ).__dict__
        }
    ]


async def execute_context_tool(
    tool_name: str,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a context engine tool."""
    try:
        from app.services.context_engine_service import get_context_engine_service

        service = get_context_engine_service()

        if tool_name == "get_context":
            query = arguments.get("query")
            rebuild = arguments.get("rebuild", False)

            if rebuild or query:
                # Build fresh profile
                profile = service.build_context_profile(query=query)
                return {
                    "success": True,
                    "profile_id": profile.profile_id,
                    "mood": profile.primary_mood.value,
                    "energy_level": profile.energy_level,
                    "stress_level": profile.stress_level,
                    "focus_level": profile.focus_level,
                    "time_of_day": profile.time_of_day.value,
                    "day_type": profile.day_type.value,
                    "calendar_load": profile.calendar_load.value,
                    "recommended_tone": profile.recommended_tone,
                    "recommended_verbosity": profile.recommended_verbosity,
                    "tool_adjustments": profile.tool_adjustments,
                    "prompt_injection": profile.prompt_injection[:100] + "..." if profile.prompt_injection and len(profile.prompt_injection) > 100 else profile.prompt_injection,
                    "specialist_preference": profile.specialist_preference,
                    "signals_used": profile.signals_used
                }
            else:
                # Get existing context
                return service.get_current_context()

        elif tool_name == "record_context_signal":
            return service.record_signal(
                signal_type=arguments["signal_type"],
                signal_value=arguments["signal_value"],
                intensity=arguments.get("intensity", 0.5),
                source=arguments.get("source", "auto_detect")
            )

        elif tool_name == "get_context_rules":
            include_inactive = arguments.get("include_inactive", False)

            try:
                from app.postgres_state import get_conn

                with get_conn() as conn:
                    with conn.cursor() as cur:
                        query = """
                            SELECT rule_name, description, conditions,
                                   tone_adjustment, verbosity_adjustment,
                                   prompt_injection, priority, enabled,
                                   trigger_count
                            FROM jarvis_context_rules
                        """
                        if not include_inactive:
                            query += " WHERE enabled = TRUE"
                        query += " ORDER BY priority ASC"

                        cur.execute(query)

                        rules = []
                        for row in cur.fetchall():
                            rules.append({
                                "name": row["rule_name"],
                                "description": row["description"],
                                "conditions": row["conditions"],
                                "tone": row["tone_adjustment"],
                                "verbosity": row["verbosity_adjustment"],
                                "priority": row["priority"],
                                "enabled": row["enabled"],
                                "triggers": row["trigger_count"]
                            })

                        return {
                            "success": True,
                            "rules": rules,
                            "count": len(rules)
                        }

            except Exception as e:
                return {"success": False, "error": str(e)}

        elif tool_name == "get_context_stats":
            return service.get_context_stats()

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"Context tool error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


CONTEXT_TOOLS = {
    "get_context",
    "record_context_signal",
    "get_context_rules",
    "get_context_stats"
}


def is_context_tool(tool_name: str) -> bool:
    """Check if a tool name is a context tool."""
    return tool_name in CONTEXT_TOOLS
