"""
Agent Message Tools - Tier 3 #9

Tools for inter-agent communication:
- send_agent_message: Send message to another agent
- get_agent_messages: Get messages for an agent
- reply_agent_message: Reply to a message
- handoff_to_specialist: Handoff context to another specialist
- get_message_stats: Get messaging statistics
- broadcast_message: Send message to all agents
"""

from typing import Dict, Any, List, Optional

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger

logger = get_logger("jarvis.tools.agent_message")


def get_agent_message_tools() -> List[Dict[str, Any]]:
    """Return agent message tool definitions."""
    return [
        {
            "name": "send_agent_message",
            "description": (
                "Sendet eine Nachricht an einen anderen Agent/Specialist. "
                "Ermöglicht Kommunikation zwischen FitJarvis, WorkJarvis, CommJarvis, SaaSJarvis."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "from_agent": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Absender-Agent"
                    },
                    "to_agent": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Empfänger-Agent"
                    },
                    "message_type": {
                        "type": "string",
                        "enum": ["request", "notification", "context_share"],
                        "description": "Art der Nachricht"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Kurze Beschreibung"
                    },
                    "content": {
                        "type": "object",
                        "description": "Nachrichteninhalt mit intent und payload"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": "Priorität (default: normal)"
                    }
                },
                "required": ["from_agent", "to_agent", "message_type", "subject", "content"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["message", "agent", "send", "communicate", "specialist"]
            ).__dict__
        },
        {
            "name": "get_agent_messages",
            "description": (
                "Ruft Nachrichten für einen Agent ab. "
                "Zeigt eingehende Nachrichten, Anfragen und Benachrichtigungen."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Für welchen Agent"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "delivered", "read", "processed"],
                        "description": "Filter nach Status"
                    },
                    "message_type": {
                        "type": "string",
                        "enum": ["request", "response", "notification", "handoff"],
                        "description": "Filter nach Typ"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max Nachrichten (default: 20)"
                    }
                },
                "required": ["agent"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["message", "agent", "inbox", "receive"]
            ).__dict__
        },
        {
            "name": "reply_agent_message",
            "description": (
                "Antwortet auf eine Agent-Nachricht. "
                "Wird verwendet um auf Anfragen zu reagieren."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "ID der Original-Nachricht"
                    },
                    "from_agent": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Antwortender Agent"
                    },
                    "content": {
                        "type": "object",
                        "description": "Antwort-Inhalt"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Optional: Antwort-Betreff"
                    }
                },
                "required": ["message_id", "from_agent", "content"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["message", "reply", "response", "answer"]
            ).__dict__
        },
        {
            "name": "handoff_to_specialist",
            "description": (
                "Übergibt Kontext an einen anderen Specialist. "
                "Nutze dies wenn ein anderer Specialist besser geeignet ist."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "from_specialist": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Aktueller Specialist"
                    },
                    "to_specialist": {
                        "type": "string",
                        "enum": ["fit", "work", "comm", "saas"],
                        "description": "Ziel-Specialist"
                    },
                    "context_summary": {
                        "type": "string",
                        "description": "Zusammenfassung des bisherigen Gesprächs"
                    },
                    "relevant_facts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Relevante Fakten für den neuen Specialist"
                    },
                    "user_mood": {
                        "type": "string",
                        "description": "Aktuelle Stimmung des Users (optional)"
                    }
                },
                "required": ["from_specialist", "to_specialist", "context_summary"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["handoff", "specialist", "switch", "übergabe"]
            ).__dict__
        },
        {
            "name": "broadcast_message",
            "description": (
                "Sendet eine Nachricht an alle Agents. "
                "Für wichtige Mitteilungen die alle betreffen."
            ),
            "category": ToolCategory.SYSTEM.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "from_agent": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Absender"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Betreff"
                    },
                    "content": {
                        "type": "object",
                        "description": "Nachrichteninhalt"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": "Priorität"
                    }
                },
                "required": ["from_agent", "subject", "content"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.SYSTEM,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["broadcast", "message", "all", "announce"]
            ).__dict__
        },
        {
            "name": "get_message_stats",
            "description": (
                "Zeigt Messaging-Statistiken: gesendete/empfangene Nachrichten, "
                "ausstehende Anfragen, Handoffs."
            ),
            "category": ToolCategory.MONITORING.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "enum": ["jarvis", "fit", "work", "comm", "saas"],
                        "description": "Optional: Stats nur für diesen Agent"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.MONITORING,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["message", "stats", "analytics", "count"]
            ).__dict__
        }
    ]


async def execute_agent_message_tool(
    tool_name: str,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute an agent message tool."""
    try:
        from app.services.agent_message_service import get_agent_message_service

        service = get_agent_message_service()

        if tool_name == "send_agent_message":
            return service.send_message(
                from_agent=arguments["from_agent"],
                to_agent=arguments["to_agent"],
                message_type=arguments["message_type"],
                subject=arguments["subject"],
                content=arguments["content"],
                priority=arguments.get("priority", "normal")
            )

        elif tool_name == "get_agent_messages":
            return service.get_messages(
                agent=arguments["agent"],
                status=arguments.get("status"),
                message_type=arguments.get("message_type"),
                limit=arguments.get("limit", 20)
            )

        elif tool_name == "reply_agent_message":
            return service.reply_to_message(
                original_message_id=arguments["message_id"],
                from_agent=arguments["from_agent"],
                content=arguments["content"],
                subject=arguments.get("subject")
            )

        elif tool_name == "handoff_to_specialist":
            return service.handoff_context(
                from_specialist=arguments["from_specialist"],
                to_specialist=arguments["to_specialist"],
                context_summary=arguments["context_summary"],
                relevant_facts=arguments.get("relevant_facts", []),
                user_mood=arguments.get("user_mood")
            )

        elif tool_name == "broadcast_message":
            return service.broadcast_message(
                from_agent=arguments["from_agent"],
                subject=arguments["subject"],
                content=arguments["content"],
                priority=arguments.get("priority", "normal")
            )

        elif tool_name == "get_message_stats":
            return service.get_message_stats(
                agent=arguments.get("agent")
            )

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"Agent message tool error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


AGENT_MESSAGE_TOOLS = {
    "send_agent_message",
    "get_agent_messages",
    "reply_agent_message",
    "handoff_to_specialist",
    "broadcast_message",
    "get_message_stats"
}


def is_agent_message_tool(tool_name: str) -> bool:
    """Check if a tool name is an agent message tool."""
    return tool_name in AGENT_MESSAGE_TOOLS
