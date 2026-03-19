"""
Specialist Agent Tools - Tier 3 #8

Tools for managing and interacting with specialist agents:
- list_specialists: Show available specialists
- get_specialist_info: Get details about a specialist
- activate_specialist: Explicitly activate a specialist
- get_specialist_stats: Get specialist usage statistics
- save_specialist_memory: Save cross-session memory
- get_specialist_memory: Retrieve specialist memory
"""

from typing import Dict, Any, List, Optional

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger

logger = get_logger("jarvis.tools.specialist")


def get_specialist_tools() -> List[Dict[str, Any]]:
    """Return specialist agent tool definitions."""
    return [
        {
            "name": "list_specialists",
            "description": (
                "Zeigt alle verfügbaren Specialist Agents: "
                "FitJarvis (Fitness/Gesundheit), WorkJarvis (Produktivität), "
                "CommJarvis (Kommunikation), SaaSJarvis (Revenue/Product-Ops). Jeder Specialist hat eigene "
                "Expertise und Tools."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["specialist", "agents", "fitjarvis", "workjarvis", "commjarvis"]
            ).__dict__
        },
        {
            "name": "get_specialist_info",
            "description": (
                "Zeigt Details über einen bestimmten Specialist Agent: "
                "Fähigkeiten, bevorzugte Tools, Wissensgebiete."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "specialist_name": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Name des Specialists (fit, work, comm, saas)"
                    }
                },
                "required": ["specialist_name"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["specialist", "info", "details", "fähigkeiten"]
            ).__dict__
        },
        {
            "name": "activate_specialist",
            "description": (
                "Aktiviert explizit einen Specialist Agent für die aktuelle Anfrage. "
                "Nutze dies wenn ein Specialist besser geeignet ist als Standard-Jarvis."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "specialist_name": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Name des zu aktivierenden Specialists"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Grund für die Aktivierung"
                    }
                },
                "required": ["specialist_name"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["specialist", "aktivieren", "wechseln", "switch"]
            ).__dict__
        },
        {
            "name": "get_specialist_stats",
            "description": (
                "Zeigt Nutzungsstatistiken für Specialist Agents: "
                "Aktivierungen, Erfolgsrate, letzte Nutzung."
            ),
            "category": ToolCategory.MONITORING.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "specialist_name": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Optional: Nur Stats für diesen Specialist"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.MONITORING,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["specialist", "statistik", "nutzung", "analytics"]
            ).__dict__
        },
        {
            "name": "save_specialist_memory",
            "description": (
                "Speichert ein Memory für einen Specialist Agent. "
                "Wird über Sessions hinweg gespeichert und beeinflusst "
                "zukünftige Specialist-Interaktionen."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "specialist_name": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Welcher Specialist"
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["goal", "preference", "pattern", "fact"],
                        "description": "Art des Memorys"
                    },
                    "key": {
                        "type": "string",
                        "description": "Eindeutiger Key (z.B. 'preferred_workout_time')"
                    },
                    "value": {
                        "type": "string",
                        "description": "Wert des Memorys"
                    },
                    "expires_days": {
                        "type": "integer",
                        "description": "Ablauf in Tagen (optional, null = permanent)"
                    }
                },
                "required": ["specialist_name", "memory_type", "key", "value"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["specialist", "memory", "speichern", "merken"]
            ).__dict__
        },
        {
            "name": "get_specialist_memory",
            "description": (
                "Ruft gespeicherte Memories eines Specialists ab. "
                "Zeigt was der Specialist über bestimmte Themen weiss."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "specialist_name": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Welcher Specialist"
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["goal", "preference", "pattern", "fact"],
                        "description": "Optional: Filter nach Memory-Typ"
                    }
                },
                "required": ["specialist_name"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["specialist", "memory", "abrufen", "wissen"]
            ).__dict__
        }
    ]


async def execute_specialist_tool(
    tool_name: str,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a specialist agent tool."""
    try:
        from app.services.specialist_agent_service import get_specialist_agent_service

        service = get_specialist_agent_service()

        if tool_name == "list_specialists":
            specialists = service.get_all_specialists()
            return {
                "success": True,
                "specialists": [
                    {
                        "name": s.name,
                        "display_name": s.display_name,
                        "description": s.description,
                        "tone": s.tone,
                        "keywords": s.keywords[:5],
                        "domains": s.domains
                    }
                    for s in specialists
                ],
                "count": len(specialists),
                "summary": (
                    f"{len(specialists)} Specialists verfügbar: "
                    f"{', '.join(s.display_name for s in specialists)}"
                )
            }

        elif tool_name == "get_specialist_info":
            name = arguments["specialist_name"]
            spec = service.get_specialist(name)

            if not spec:
                return {"success": False, "error": f"Specialist '{name}' nicht gefunden"}

            return {
                "success": True,
                "specialist": {
                    "name": spec.name,
                    "display_name": spec.display_name,
                    "description": spec.description,
                    "persona": spec.persona_prompt[:200] + "..." if len(spec.persona_prompt) > 200 else spec.persona_prompt,
                    "tone": spec.tone,
                    "verbosity": spec.verbosity,
                    "keywords": spec.keywords,
                    "domains": spec.domains,
                    "preferred_tools": spec.preferred_tools,
                    "proactive_hints": spec.proactive_hints
                }
            }

        elif tool_name == "activate_specialist":
            name = arguments["specialist_name"]
            reason = arguments.get("reason", "Explicit activation")

            spec = service.get_specialist(name)
            if not spec:
                return {"success": False, "error": f"Specialist '{name}' nicht gefunden"}

            # Get context for the specialist
            context = service.get_specialist_context(spec, reason)

            return {
                "success": True,
                "activated": spec.display_name,
                "persona_prompt": spec.persona_prompt,
                "preferred_tools": spec.preferred_tools,
                "knowledge_count": len(context.knowledge),
                "memory_count": len(context.memory),
                "message": f"{spec.display_name} aktiviert. Persona und Tools angepasst."
            }

        elif tool_name == "get_specialist_stats":
            name = arguments.get("specialist_name")
            return service.get_specialist_stats(name)

        elif tool_name == "save_specialist_memory":
            name = arguments["specialist_name"]
            memory_type = arguments["memory_type"]
            key = arguments["key"]
            value = arguments["value"]
            expires_days = arguments.get("expires_days")

            service.save_memory(
                specialist_name=name,
                memory_type=memory_type,
                key=key,
                value=value,
                expires_days=expires_days
            )

            return {
                "success": True,
                "specialist": name,
                "memory_type": memory_type,
                "key": key,
                "expires": f"in {expires_days} Tagen" if expires_days else "permanent",
                "message": f"Memory '{key}' für {name} gespeichert"
            }

        elif tool_name == "get_specialist_memory":
            name = arguments["specialist_name"]
            memory_type = arguments.get("memory_type")

            memories = service._get_specialist_memory(name)

            if memory_type:
                memories = [m for m in memories if m["type"] == memory_type]

            return {
                "success": True,
                "specialist": name,
                "memories": memories,
                "count": len(memories)
            }

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"Specialist tool error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


SPECIALIST_TOOLS = {
    "list_specialists",
    "get_specialist_info",
    "activate_specialist",
    "get_specialist_stats",
    "save_specialist_memory",
    "get_specialist_memory"
}


def is_specialist_tool(tool_name: str) -> bool:
    """Check if a tool name is a specialist tool."""
    return tool_name in SPECIALIST_TOOLS
