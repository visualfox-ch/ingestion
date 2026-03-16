"""
Decision Support Tools - Tier 1 Quick Win

Provides Jarvis with tools to give data-driven decision support
based on historical patterns and observations.

Tools:
- analyze_decision: Analyze a decision with historical data
- find_similar_situations: Find similar past situations
- record_decision_outcome: Record decision outcomes for learning
- get_decision_stats: Get decision support statistics
"""

from typing import Dict, Any, List, Optional

from app.tools.base import ToolCategory, ToolMetadata
from app.observability import get_logger

logger = get_logger("jarvis.tools.decision_support")


def get_decision_support_tools() -> List[Dict[str, Any]]:
    """Return decision support tool definitions."""
    return [
        {
            "name": "analyze_decision",
            "description": (
                "Analysiert eine Entscheidung basierend auf historischen Daten. "
                "Gibt Empfehlungen mit Erfolgsraten basierend auf ähnlichen Situationen. "
                "Beispiel: 'Soll ich heute Abend Sport machen oder morgen früh?'"
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "decision_query": {
                        "type": "string",
                        "description": "Die Entscheidungsfrage"
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste der Optionen (optional, wird aus query extrahiert)"
                    },
                    "context": {
                        "type": "object",
                        "description": "Kontextinformationen (z.B. Energielevel, Zeitplan)"
                    }
                },
                "required": ["decision_query"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=10,
                keywords=["entscheidung", "decision", "soll ich", "oder", "empfehlung"]
            ).__dict__
        },
        {
            "name": "find_similar_situations",
            "description": (
                "Findet ähnliche vergangene Situationen basierend auf Schlüsselwörtern. "
                "Hilft zu verstehen, was in ähnlichen Situationen passiert ist."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Schlüsselwörter für die Suche"
                    },
                    "context": {
                        "type": "object",
                        "description": "Optionaler Kontext"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximale Anzahl Ergebnisse",
                        "default": 10
                    }
                },
                "required": ["keywords"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["ähnlich", "similar", "situation", "muster"]
            ).__dict__
        },
        {
            "name": "record_decision_outcome",
            "description": (
                "Zeichnet das Ergebnis einer Entscheidung auf für zukünftiges Lernen. "
                "Wichtig für den Aufbau der Wissensbasis."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "description": "Die getroffene Entscheidung"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Was als Ergebnis passiert ist"
                    },
                    "outcome_type": {
                        "type": "string",
                        "enum": ["positive", "negative", "neutral"],
                        "description": "Art des Ergebnisses"
                    },
                    "time_delta_minutes": {
                        "type": "integer",
                        "description": "Zeit zwischen Entscheidung und Ergebnis in Minuten"
                    },
                    "context": {
                        "type": "object",
                        "description": "Kontextinformationen"
                    }
                },
                "required": ["decision", "outcome"]
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=5,
                keywords=["aufzeichnen", "record", "ergebnis", "outcome"]
            ).__dict__
        },
        {
            "name": "get_decision_stats",
            "description": (
                "Gibt Statistiken über die Decision Support Wissensbasis. "
                "Zeigt wie viele Muster und Beobachtungen vorhanden sind."
            ),
            "category": ToolCategory.KNOWLEDGE.value,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            },
            "metadata": ToolMetadata(
                category=ToolCategory.KNOWLEDGE,
                requires_auth=False,
                is_async=False,
                timeout_seconds=3,
                keywords=["statistik", "stats", "decision"]
            ).__dict__
        }
    ]


async def execute_decision_support_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    user_id: str = "micha",
    session_id: str = None
) -> Dict[str, Any]:
    """Execute a decision support tool."""
    try:
        from app.services.decision_support_service import get_decision_support

        service = get_decision_support()

        if tool_name == "analyze_decision":
            result = service.analyze_decision(
                user_id=user_id,
                decision_query=arguments["decision_query"],
                options=arguments.get("options"),
                context=arguments.get("context")
            )

            # Format for Jarvis
            if result.get("recommendation"):
                summary = (
                    f"**Empfehlung:** {result['recommendation']}\n\n"
                    f"**Begründung:** {result['reasoning']}\n\n"
                    f"**Confidence:** {result['confidence']*100:.0f}%\n"
                    f"**Datenbasis:** {result['total_observations']} Beobachtungen"
                )
            else:
                summary = (
                    f"**Keine klare Empfehlung möglich.**\n\n"
                    f"**Begründung:** {result['reasoning']}\n"
                    f"**Datenbasis:** {result['total_observations']} Beobachtungen"
                )

            return {
                "success": True,
                "summary": summary,
                "details": result
            }

        elif tool_name == "find_similar_situations":
            situations = service.find_similar_situations(
                user_id=user_id,
                query_keywords=arguments["keywords"],
                context=arguments.get("context"),
                limit=arguments.get("limit", 10)
            )

            formatted = []
            for s in situations:
                formatted.append({
                    "pattern": f"{s.cause} → {s.effect}",
                    "confidence": f"{s.confidence*100:.0f}%",
                    "observations": s.evidence_count,
                    "outcome_type": s.outcome_type
                })

            return {
                "success": True,
                "count": len(situations),
                "similar_situations": formatted,
                "summary": f"Gefunden: {len(situations)} ähnliche Situationen"
            }

        elif tool_name == "record_decision_outcome":
            # Map outcome_type to internal types
            outcome_type_map = {
                "positive": "outcome",
                "negative": "warning",
                "neutral": "outcome"
            }

            result = service.record_decision_outcome(
                user_id=user_id,
                decision=arguments["decision"],
                outcome=arguments["outcome"],
                outcome_type=outcome_type_map.get(
                    arguments.get("outcome_type", "neutral"),
                    "outcome"
                ),
                time_delta_minutes=arguments.get("time_delta_minutes"),
                context=arguments.get("context"),
                session_id=session_id
            )

            return {
                "success": result.get("recorded", False),
                "message": result.get("message", "Aufzeichnung fehlgeschlagen"),
                "is_new_pattern": result.get("is_new_pattern", False)
            }

        elif tool_name == "get_decision_stats":
            stats = service.get_stats(user_id=user_id)

            summary = (
                f"**Decision Support Status:** {stats['recommendation_readiness']}\n\n"
                f"- Patterns: {stats['total_patterns']} "
                f"({stats['high_confidence_patterns']} mit hoher Confidence)\n"
                f"- Beobachtungen: {stats['total_observations']}\n"
                f"- Letzte 7 Tage: {stats['decisions_last_7_days']} Entscheidungen"
            )

            return {
                "success": True,
                "summary": summary,
                "stats": stats
            }

        else:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }

    except Exception as e:
        logger.error(f"Decision support tool error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


# Tool category check for tool_executor
DECISION_SUPPORT_TOOLS = {
    "analyze_decision",
    "find_similar_situations",
    "record_decision_outcome",
    "get_decision_stats"
}


def is_decision_support_tool(tool_name: str) -> bool:
    """Check if a tool name is a decision support tool."""
    return tool_name in DECISION_SUPPORT_TOOLS
