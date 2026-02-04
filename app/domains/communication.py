"""
Communication Coaching Domain

Specialized coaching for:
- Difficult conversations
- Conflict resolution
- Giving/receiving feedback
- Team communication
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class CommunicationDomain(BaseDomain):
    """Communication and conflict coaching domain."""

    @property
    def domain_id(self) -> str:
        return "communication"

    @property
    def name(self) -> str:
        return "Communication Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build communication-specific context."""
        context_parts = [
            "=== COMMUNICATION COACHING MODE ===",
            "",
            "Du bist ein Communication Coach für schwierige Gespräche und Konflikte.",
            "",
            "## Frameworks",
            "",
            "### SBI (Situation-Behavior-Impact)",
            "- Situation: Wann/wo passierte es?",
            "- Behavior: Was genau wurde getan/gesagt?",
            "- Impact: Welche Auswirkung hatte das?",
            "",
            "### DESC (Describe-Express-Specify-Consequences)",
            "- Describe: Situation neutral beschreiben",
            "- Express: Eigene Gefühle ausdrücken",
            "- Specify: Konkrete Änderung vorschlagen",
            "- Consequences: Positive Konsequenzen aufzeigen",
            "",
            "### NVC (Nonviolent Communication)",
            "- Observation: Was beobachte ich?",
            "- Feeling: Was fühle ich dabei?",
            "- Need: Welches Bedürfnis steckt dahinter?",
            "- Request: Was wünsche ich mir konkret?",
            "",
            "## Output-Format für Gespräche",
            "```",
            "**Ziel:** [Was soll erreicht werden?]",
            "",
            "**Opening:**",
            "[Wie das Gespräch starten]",
            "",
            "**Kernbotschaft:**",
            "[Hauptpunkt mit Formulierungsvorschlag]",
            "",
            "**Mögliche Einwände:**",
            "- Wenn: '[Einwand]' → Dann: '[Antwort]'",
            "",
            "**Closing:**",
            "[Nächste Schritte vereinbaren]",
            "```",
            "",
            "## Grundprinzipien",
            "- Verhalten kritisieren, nicht Person",
            "- Ich-Botschaften statt Du-Vorwürfe",
            "- Zuhören vor Antworten",
            "- Gemeinsame Lösung suchen",
        ]

        # Add relationship context if available
        if ctx.user_profile:
            comm_style = ctx.user_profile.get("communication_style", "")
            if comm_style:
                context_parts.append(f"\nDein Kommunikationsstil: {comm_style}")

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Communication uses email/chat search for context."""
        return ["search_emails", "search_chats"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract insights about communication patterns."""
        insights = []
        message_lower = message.lower()

        # Track conflict types
        conflict_types = {
            "chef": "hierarchical",
            "kollege": "peer",
            "team": "team",
            "kunde": "client",
            "partner": "personal",
            "mitarbeiter": "direct_report",
        }

        for keyword, conflict_type in conflict_types.items():
            if keyword in message_lower:
                insights.append({
                    "type": "conflict_context",
                    "relationship": conflict_type,
                    "timestamp": datetime.utcnow().isoformat()
                })
                break

        # Track communication challenges
        challenges = ["feedback", "kritik", "konflikt", "schwierig", "ärger", "frustration"]
        for challenge in challenges:
            if challenge in message_lower:
                insights.append({
                    "type": "communication_challenge",
                    "challenge": challenge,
                    "timestamp": datetime.utcnow().isoformat()
                })

        return insights

    def get_cross_domain_patterns(self, ctx: DomainContext) -> List[Dict[str, Any]]:
        """Patterns useful for work domain."""
        return [
            {
                "source_domain": "communication",
                "target_domain": "work",
                "pattern_type": "conflict_resolution",
                "content": "Communication frameworks can help with stakeholder management"
            }
        ]

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """Communication session start."""
        return "Bevor wir starten: Atme kurz durch. Klarheit kommt aus Ruhe."

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """Communication session end."""
        return "Wichtig: Das Gespräch zeitnah führen. Je länger du wartest, desto schwerer wird es."


# Singleton instance
communication_domain = CommunicationDomain()
