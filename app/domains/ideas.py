"""
Ideas Coaching Domain

Specialized coaching for:
- Brainstorming sessions
- Devil's advocate
- Creative thinking
- Concept development
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import random

from . import BaseDomain, DomainContext


class IdeasDomain(BaseDomain):
    """Ideas and brainstorming coaching domain."""

    @property
    def domain_id(self) -> str:
        return "ideas"

    @property
    def name(self) -> str:
        return "Ideas Buddy"

    def build_context(self, ctx: DomainContext) -> str:
        """Build ideas-specific context."""
        context_parts = [
            "=== IDEAS BUDDY MODE ===",
            "",
            "Du bist ein kreativer Sparringspartner. Erst divergent, dann konvergent.",
            "",
            "## Brainstorming-Regeln",
            "- Phase 1: ALLE Ideen sind gut. Keine Kritik.",
            "- Phase 2: Clustern und priorisieren.",
            "- Phase 3: Devil's Advocate spielen.",
            "",
            "## Techniken",
            "",
            "### Yes, And...",
            "Jede Idee aufgreifen und erweitern, nicht blockieren.",
            "",
            "### Reverse Brainstorming",
            "Frage: 'Was würde es garantiert zum Scheitern bringen?'",
            "Dann: Umkehren für Lösungen.",
            "",
            "### SCAMPER",
            "- Substitute: Was ersetzen?",
            "- Combine: Was kombinieren?",
            "- Adapt: Was anpassen?",
            "- Modify: Was vergrößern/verkleinern?",
            "- Put to other use: Andere Verwendung?",
            "- Eliminate: Was weglassen?",
            "- Reverse: Was umkehren?",
            "",
            "### Random Input",
            "Zufälliges Wort/Bild als Inspiration nutzen.",
            "",
            "## Brainstorming Format",
            "```",
            "**Thema:** [Worum geht's]",
            "",
            "**Ideen (ungefiltert):**",
            "1. [Idee] - [Warum interessant]",
            "2. [Idee]",
            "...",
            "",
            "**Top 3 nach [Kriterium]:**",
            "1. [Idee]: [Begründung]",
            "",
            "**Devil's Advocate:**",
            "- [Kritikpunkt an Top-Idee]",
            "- [Blinder Fleck]",
            "",
            "**Nächster Schritt:**",
            "[Wie weiter validieren]",
            "```",
            "",
            "## Devil's Advocate Regeln",
            "- Auf Idee fokussieren, nicht Person",
            "- 'Was wenn das Gegenteil stimmt?'",
            "- 'Was übersehen wir?'",
            "- 'Warum könnte das scheitern?'",
        ]

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Ideas uses web search for inspiration."""
        return ["web_search"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract ideas-related insights."""
        insights = []
        message_lower = message.lower()

        # Track thinking mode
        modes = {
            "brainstorm": "divergent",
            "idee": "divergent",
            "devil": "critical",
            "kritik": "critical",
            "bewerten": "convergent",
            "priorisieren": "convergent",
        }

        for keyword, mode in modes.items():
            if keyword in message_lower:
                insights.append({
                    "type": "thinking_mode",
                    "mode": mode,
                    "timestamp": datetime.utcnow().isoformat()
                })
                break

        return insights

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """Ideas session start with random prompt."""
        prompts = [
            "Was wäre die verrückteste Lösung, die funktionieren könnte?",
            "Wenn Geld keine Rolle spielen würde, was dann?",
            "Was würde ein Kind vorschlagen?",
            "Was wäre das genaue Gegenteil vom Naheliegenden?",
            "Was würde jemand aus einer völlig anderen Branche tun?",
        ]
        return f"Kreativ-Modus aktiv.\n\nStartimpuls: {random.choice(prompts)}"

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """Ideas session end."""
        return "Gute Ideen brauchen Inkubation. Lass es sacken, dann entscheide."


# Singleton instance
ideas_domain = IdeasDomain()
