"""
LinkedIn Coaching Domain

Specialized coaching for:
- Content creation (posts, carousels, comments)
- Profile optimization
- Engagement strategies
- Personal branding
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class LinkedInDomain(BaseDomain):
    """LinkedIn content and profile coaching domain."""

    @property
    def domain_id(self) -> str:
        return "linkedin"

    @property
    def name(self) -> str:
        return "LinkedIn Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build LinkedIn-specific context."""
        context_parts = [
            "=== LINKEDIN COACHING MODE ===",
            "",
            "Du bist ein LinkedIn Content Coach. Fokus auf authentische, wertvolle Inhalte.",
            "",
        ]

        # Add user-specific context if available
        if ctx.user_profile:
            industry = ctx.user_profile.get("industry", "")
            expertise = ctx.user_profile.get("expertise", [])
            tone = ctx.user_profile.get("preferred_tone", "professional")

            if industry:
                context_parts.append(f"Branche: {industry}")
            if expertise:
                context_parts.append(f"Expertise: {', '.join(expertise)}")
            context_parts.append(f"Bevorzugter Ton: {tone}")
            context_parts.append("")

        # Add goals if set
        if ctx.goals:
            context_parts.append("Aktuelle Ziele:")
            for goal in ctx.goals:
                context_parts.append(f"- {goal}")
            context_parts.append("")

        # Content guidelines
        context_parts.extend([
            "## Content-Formate",
            "",
            "### Text-Post",
            "- Hook (erste Zeile = Stopper)",
            "- Story/Value (persönlich, konkret)",
            "- Learning/Takeaway",
            "- CTA (Frage, Aufforderung)",
            "- 3-5 Hashtags am Ende",
            "",
            "### Carousel",
            "- Slide 1: Hook + Versprechen",
            "- Slides 2-8: Ein Punkt pro Slide",
            "- Letzte Slide: Zusammenfassung + CTA",
            "",
            "### Comment Strategy",
            "- Erste 30 Minuten: Auf andere Posts kommentieren",
            "- Eigene Kommentare: Wert hinzufügen, nicht nur 'Great post!'",
            "",
            "## Output-Format für Posts",
            "```",
            "**Hook:**",
            "[Erste Zeile]",
            "",
            "**Content:**",
            "[Hauptinhalt]",
            "",
            "**CTA:**",
            "[Call-to-Action]",
            "",
            "**Hashtags:** #tag1 #tag2 #tag3",
            "```",
        ])

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """LinkedIn uses web search for trends."""
        return ["web_search"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract insights about content preferences."""
        insights = []

        # Track content type preferences
        content_keywords = {
            "carousel": "carousel",
            "post": "text_post",
            "comment": "comment",
            "artikel": "article",
            "video": "video",
        }

        message_lower = message.lower()
        for keyword, content_type in content_keywords.items():
            if keyword in message_lower:
                insights.append({
                    "type": "content_preference",
                    "content_type": content_type,
                    "timestamp": datetime.utcnow().isoformat()
                })
                break

        # Track topics
        topic_keywords = ["leadership", "tech", "karriere", "startup", "ai", "productivity"]
        for topic in topic_keywords:
            if topic in message_lower:
                insights.append({
                    "type": "topic_interest",
                    "topic": topic,
                    "timestamp": datetime.utcnow().isoformat()
                })

        return insights

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """LinkedIn session greeting."""
        hour = datetime.now().hour

        if 6 <= hour < 10:
            timing = "Morgens posten hat gute Reichweite."
        elif 11 <= hour < 14:
            timing = "Lunchtime = gute Engagement-Zeit."
        elif 17 <= hour < 20:
            timing = "Abends gut für thoughtful content."
        else:
            timing = ""

        tips = [
            "Tipp: Konsistenz > Perfektion. Lieber regelmäßig okay als selten perfekt.",
            "Tipp: Persönliche Stories performen besser als generische Tipps.",
            "Tipp: Erst Wert geben, dann nehmen.",
        ]

        import random
        tip = random.choice(tips)

        return f"{timing}\n\n{tip}" if timing else tip

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """LinkedIn session summary."""
        return "Denk daran: Authentizität schlägt Perfektion. Poste, was dir wichtig ist."


# Singleton instance
linkedin_domain = LinkedInDomain()
