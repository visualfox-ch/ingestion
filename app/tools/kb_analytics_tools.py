"""
Knowledge Base Analytics Tools - Tier 2 Feature

Tools for analyzing and optimizing the knowledge base:
- get_kb_health: Overall KB health report
- get_source_rankings: Ranked sources by quality
- get_knowledge_gaps: Find missing knowledge areas
- mark_gap_resolved: Mark a gap as resolved
"""

from typing import Dict, Any, List, Optional

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger

logger = get_logger("jarvis.tools.kb_analytics")


def get_kb_analytics_tools() -> List[Dict[str, Any]]:
    """Return KB analytics tool definitions."""
    return [
        {
            "name": "get_kb_health",
            "description": (
                "Gibt einen Gesundheitsbericht der Knowledge Base: "
                "aktive vs. ungenutzte Einträge, Durchschnitts-Relevanz, "
                "Wissenslücken, und Optimierungsempfehlungen."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Analysezeitraum in Tagen (default: 30)"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["knowledge", "health", "analyse", "qualität", "kb"]
            ).__dict__
        },
        {
            "name": "get_source_rankings",
            "description": (
                "Zeigt Ranking der Wissensquellen nach Qualität: "
                "welche Quellen liefern die besten Antworten?"
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max Anzahl Quellen (default: 20)"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["quellen", "sources", "ranking", "qualität"]
            ).__dict__
        },
        {
            "name": "get_knowledge_gaps",
            "description": (
                "Findet Wissenslücken: Themen die häufig gefragt werden "
                "aber keine guten Antworten haben."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Filter nach Priorität"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max Anzahl Lücken (default: 20)"
                    }
                },
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["lücken", "gaps", "fehlt", "missing"]
            ).__dict__
        },
        {
            "name": "mark_gap_resolved",
            "description": (
                "Markiert eine Wissenslücke als gelöst "
                "(z.B. nachdem neues Wissen hinzugefügt wurde)."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "gap_id": {
                        "type": "integer",
                        "description": "ID der Wissenslücke"
                    }
                },
                "required": ["gap_id"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=3,
                keywords=["lücke", "gap", "resolved", "gelöst"]
            ).__dict__
        }
    ]


async def execute_kb_analytics_tool(
    tool_name: str,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a KB analytics tool."""
    try:
        from app.services.knowledge_analytics import get_knowledge_analytics

        service = get_knowledge_analytics()

        if tool_name == "get_kb_health":
            days = arguments.get("days", 30)
            result = service.get_kb_health_report(days=days)

            if result.get("success"):
                # Format summary
                health = result.get("health_score", 0)
                status = "Gut" if health >= 0.7 else "OK" if health >= 0.5 else "Verbesserungsbedarf"

                result["summary"] = (
                    f"KB Health: {health:.0%} ({status})\n"
                    f"Aktive Einträge: {result.get('active_entries', 0)}\n"
                    f"Offene Lücken: {result.get('unresolved_gaps', 0)}"
                )

            return result

        elif tool_name == "get_source_rankings":
            limit = arguments.get("limit", 20)
            return service.get_source_rankings(limit=limit)

        elif tool_name == "get_knowledge_gaps":
            priority = arguments.get("priority")
            limit = arguments.get("limit", 20)
            return service.get_knowledge_gaps(priority=priority, limit=limit)

        elif tool_name == "mark_gap_resolved":
            gap_id = arguments["gap_id"]
            success = service.mark_gap_resolved(gap_id)
            return {
                "success": success,
                "gap_id": gap_id,
                "message": "Lücke als gelöst markiert" if success else "Fehler"
            }

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"KB analytics tool error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


KB_ANALYTICS_TOOLS = {
    "get_kb_health",
    "get_source_rankings",
    "get_knowledge_gaps",
    "mark_gap_resolved"
}


def is_kb_analytics_tool(tool_name: str) -> bool:
    """Check if a tool name is a KB analytics tool."""
    return tool_name in KB_ANALYTICS_TOOLS
