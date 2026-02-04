"""
Nutrition Coaching Domain

Specialized coaching for:
- Meal planning
- Habit building
- 80/20 eating principle
- Sustainable nutrition changes
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class NutritionDomain(BaseDomain):
    """Nutrition and eating habits coaching domain."""

    @property
    def domain_id(self) -> str:
        return "nutrition"

    @property
    def name(self) -> str:
        return "Nutrition Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build nutrition-specific context."""
        context_parts = [
            "=== NUTRITION COACHING MODE ===",
            "",
            "Du bist ein pragmatischer Nutrition Coach. 80/20 Prinzip: Gut genug ist gut genug.",
            "",
        ]

        # Add user nutrition profile
        if ctx.user_profile:
            diet_type = ctx.user_profile.get("diet_type", "")
            allergies = ctx.user_profile.get("allergies", [])
            dislikes = ctx.user_profile.get("food_dislikes", [])
            goals = ctx.user_profile.get("nutrition_goals", [])

            if diet_type:
                context_parts.append(f"Ernährungsform: {diet_type}")
            if allergies:
                context_parts.append(f"Allergien/Unverträglichkeiten: {', '.join(allergies)}")
            if dislikes:
                context_parts.append(f"Mag nicht: {', '.join(dislikes)}")
            if goals:
                context_parts.append(f"Ziele: {', '.join(goals)}")
            context_parts.append("")

        context_parts.extend([
            "## Prinzipien",
            "- Keine Diäten, sondern Gewohnheiten",
            "- Eine Änderung zur Zeit",
            "- Protein bei jeder Mahlzeit",
            "- Gemüse = Volumen ohne Kalorien",
            "- Meal Prep = Erfolg vorbereiten",
            "",
            "## Meal Plan Format",
            "```",
            "**Ziel:** [Was erreichen?]",
            "",
            "**Wochenbasis:**",
            "- Frühstück: [2-3 Optionen]",
            "- Lunch: [2-3 Optionen]",
            "- Dinner: [2-3 Optionen]",
            "- Snacks: [Optionen]",
            "",
            "**Prep-Liste (Sonntag):**",
            "- [ ] [Vorbereitung 1]",
            "- [ ] [Vorbereitung 2]",
            "",
            "**Diese Woche fokussieren:**",
            "[Eine konkrete Gewohnheit]",
            "```",
            "",
            "## Makro-Richtlinien (vereinfacht)",
            "- Protein: Handfläche pro Mahlzeit",
            "- Gemüse: 2 Fäuste pro Mahlzeit",
            "- Carbs: 1 Handvoll (je nach Aktivität)",
            "- Fett: 1 Daumen",
            "",
            "## Habit Stacking",
            "- Neue Gewohnheit an bestehende koppeln",
            "- Beispiel: 'Nach dem Kaffee trinke ich ein Glas Wasser'",
        ])

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Nutrition uses web search for recipes/info."""
        return ["web_search"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract nutrition-related insights."""
        insights = []
        message_lower = message.lower()

        # Track meal focus
        meals = ["frühstück", "lunch", "abendessen", "snack", "meal prep"]
        for meal in meals:
            if meal in message_lower:
                insights.append({
                    "type": "meal_focus",
                    "meal": meal,
                    "timestamp": datetime.utcnow().isoformat()
                })

        # Track nutrition goals
        goals = ["abnehmen", "zunehmen", "muskelaufbau", "energie", "gesund"]
        for goal in goals:
            if goal in message_lower:
                insights.append({
                    "type": "nutrition_goal",
                    "goal": goal,
                    "timestamp": datetime.utcnow().isoformat()
                })

        # Track challenges
        challenges = ["heißhunger", "süß", "snacking", "stress", "zeit"]
        for challenge in challenges:
            if challenge in message_lower:
                insights.append({
                    "type": "nutrition_challenge",
                    "challenge": challenge,
                    "timestamp": datetime.utcnow().isoformat()
                })

        return insights

    def get_cross_domain_patterns(self, ctx: DomainContext) -> List[Dict[str, Any]]:
        """Patterns useful for fitness domain."""
        return [
            {
                "source_domain": "nutrition",
                "target_domain": "fitness",
                "pattern_type": "recovery_nutrition",
                "content": "Nutrition habits affect training recovery and energy"
            }
        ]

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """Nutrition session start."""
        hour = datetime.now().hour

        if 6 <= hour < 10:
            return "Guten Morgen! Frühstück-Fragen oder Planung für den Tag?"
        elif 11 <= hour < 14:
            return "Lunch-Zeit! Was gibt's heute oder was brauchst du?"
        elif 17 <= hour < 20:
            return "Abendessen-Planung oder Quick-Wins für heute Abend?"
        else:
            return "Was beschäftigt dich bei der Ernährung?"

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """Nutrition session end."""
        return "Denk dran: Perfekt ist der Feind von gut. 80% reicht."


# Singleton instance
nutrition_domain = NutritionDomain()
