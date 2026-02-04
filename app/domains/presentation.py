"""
Presentation Coaching Domain

Specialized coaching for:
- Presentation structure
- Storytelling
- Slide design principles
- Delivery coaching
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class PresentationDomain(BaseDomain):
    """Presentation and public speaking coaching domain."""

    @property
    def domain_id(self) -> str:
        return "presentation"

    @property
    def name(self) -> str:
        return "Presentation Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build presentation-specific context."""
        context_parts = [
            "=== PRESENTATION COACHING MODE ===",
            "",
            "Du bist ein Presentation Coach. Eine Kernbotschaft. Story first.",
            "",
            "## Struktur-Framework",
            "",
            "### Hook (10% der Zeit)",
            "- Provokante Frage",
            "- Überraschende Statistik",
            "- Persönliche Story",
            "- Kontrast/Spannung",
            "",
            "### Problem (20% der Zeit)",
            "- Pain Point des Publikums",
            "- Warum es relevant ist",
            "- Was auf dem Spiel steht",
            "",
            "### Solution (40% der Zeit)",
            "- Dein Vorschlag/Idee/Produkt",
            "- Wie es funktioniert",
            "- Warum es anders ist",
            "",
            "### Evidence (20% der Zeit)",
            "- Case Study / Beispiel",
            "- Daten / Social Proof",
            "- Demo (wenn möglich)",
            "",
            "### CTA (10% der Zeit)",
            "- Ein klarer nächster Schritt",
            "- Einfach zu merken",
            "- Konkrete Aufforderung",
            "",
            "## Outline Format",
            "```",
            "**Titel:** [Hook-Titel]",
            "**Zielgruppe:** [Wer]",
            "**Dauer:** [X Minuten]",
            "**Kernbotschaft:** [1 Satz]",
            "",
            "**Struktur:**",
            "",
            "1. **Opening (X min):**",
            "   - Hook: [Frage/Stat/Story]",
            "",
            "2. **Problem (X min):**",
            "   - [Pain Point]",
            "",
            "3. **Solution (X min):**",
            "   - [Vorschlag]",
            "",
            "4. **Evidence (X min):**",
            "   - [Beispiel/Case]",
            "",
            "5. **CTA (X min):**",
            "   - [Aufforderung]",
            "",
            "**Speaker Notes pro Slide:**",
            "Slide 1: [Was sagen, nicht ablesen]",
            "```",
            "",
            "## Slide Design Prinzipien",
            "- 1 Idee pro Slide",
            "- Max 6 Worte pro Bullet",
            "- Bilder > Text",
            "- Keine Textwände",
            "",
            "## Delivery Tipps",
            "- Pausen nutzen (nach wichtigen Punkten)",
            "- Energie am Anfang hoch",
            "- Augenkontakt (Dreiecke im Raum)",
            "- Langsamer als es sich anfühlt",
        ]

        # Add audience context if available
        if ctx.user_profile:
            typical_audience = ctx.user_profile.get("typical_audience", "")
            if typical_audience:
                context_parts.append(f"\nTypisches Publikum: {typical_audience}")

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Presentation uses web search and email for context."""
        return ["web_search", "search_emails"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract presentation-related insights."""
        insights = []
        message_lower = message.lower()

        # Track presentation type
        types = {
            "pitch": "pitch",
            "keynote": "keynote",
            "workshop": "workshop",
            "meeting": "meeting",
            "webinar": "webinar",
            "vortrag": "talk",
        }

        for keyword, pres_type in types.items():
            if keyword in message_lower:
                insights.append({
                    "type": "presentation_type",
                    "pres_type": pres_type,
                    "timestamp": datetime.utcnow().isoformat()
                })
                break

        # Track audience type
        audiences = ["investoren", "team", "kunden", "management", "konferenz"]
        for audience in audiences:
            if audience in message_lower:
                insights.append({
                    "type": "audience",
                    "audience": audience,
                    "timestamp": datetime.utcnow().isoformat()
                })

        return insights

    def get_cross_domain_patterns(self, ctx: DomainContext) -> List[Dict[str, Any]]:
        """Patterns useful for linkedin domain."""
        return [
            {
                "source_domain": "presentation",
                "target_domain": "linkedin",
                "pattern_type": "content_structure",
                "content": "Presentation structure works for LinkedIn posts too: Hook-Problem-Solution-CTA"
            }
        ]

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """Presentation session start."""
        return "Erst die Kernbotschaft: Was soll das Publikum tun/denken/fühlen NACH der Präsentation?"

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """Presentation session end."""
        return "Practice out loud. Minimum 3x durchsprechen vor der echten Präsentation."


# Singleton instance
presentation_domain = PresentationDomain()
