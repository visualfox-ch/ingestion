"""
Fitness Coaching Domain

Specialized coaching for:
- Workout planning
- Progressive overload
- Recovery optimization
- Movement habits
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class FitnessDomain(BaseDomain):
    """Fitness and training coaching domain."""

    @property
    def domain_id(self) -> str:
        return "fitness"

    @property
    def name(self) -> str:
        return "Fitness Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build fitness-specific context."""
        context_parts = [
            "=== FITNESS COACHING MODE ===",
            "",
            "Du bist ein pragmatischer Fitness Coach. Konsistenz > Perfektion.",
            "",
        ]

        # Add user fitness profile
        if ctx.user_profile:
            fitness_level = ctx.user_profile.get("fitness_level", "")
            goals = ctx.user_profile.get("fitness_goals", [])
            equipment = ctx.user_profile.get("equipment", [])
            restrictions = ctx.user_profile.get("restrictions", [])

            if fitness_level:
                context_parts.append(f"Fitness-Level: {fitness_level}")
            if goals:
                context_parts.append(f"Ziele: {', '.join(goals)}")
            if equipment:
                context_parts.append(f"Equipment: {', '.join(equipment)}")
            if restrictions:
                context_parts.append(f"Einschränkungen: {', '.join(restrictions)}")
            context_parts.append("")

        context_parts.extend([
            "## Prinzipien",
            "- Progressive Overload: Langsam steigern",
            "- Recovery ist Training: Schlaf, Ernährung, Stress",
            "- Compound Movements first: Squat, Deadlift, Press, Pull",
            "- Minimum Effective Dose: Weniger ist oft mehr",
            "",
            "## Workout-Format",
            "```",
            "**Ziel:** [Kraft/Ausdauer/Mobility]",
            "**Dauer:** [X Minuten]",
            "**Equipment:** [Was benötigt]",
            "",
            "**Warm-up (5 min):**",
            "- [Übung 1]",
            "- [Übung 2]",
            "",
            "**Main ([X] min):**",
            "- [Übung]: [Sets] x [Reps] @ [RPE/Gewicht]",
            "",
            "**Cool-down (5 min):**",
            "- [Stretch/Mobility]",
            "```",
            "",
            "## Recovery-Checkliste",
            "- Schlaf: 7-9 Stunden",
            "- Protein: ~1.6g/kg Körpergewicht",
            "- Hydration: ~3L Wasser",
            "- Stress: Recovery = Training + Rest - Stress",
        ])

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Fitness uses web search and calendar."""
        return ["web_search", "calendar_today"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract fitness-related insights."""
        insights = []
        message_lower = message.lower()

        # Track workout types
        workout_types = {
            "kraft": "strength",
            "cardio": "cardio",
            "hiit": "hiit",
            "yoga": "yoga",
            "mobility": "mobility",
            "laufen": "running",
            "schwimmen": "swimming",
        }

        for keyword, workout_type in workout_types.items():
            if keyword in message_lower:
                insights.append({
                    "type": "workout_preference",
                    "workout_type": workout_type,
                    "timestamp": datetime.utcnow().isoformat()
                })

        # Track body focus
        body_parts = ["beine", "rücken", "brust", "arme", "schulter", "core", "ganzkörper"]
        for part in body_parts:
            if part in message_lower:
                insights.append({
                    "type": "body_focus",
                    "body_part": part,
                    "timestamp": datetime.utcnow().isoformat()
                })

        return insights

    def get_cross_domain_patterns(self, ctx: DomainContext) -> List[Dict[str, Any]]:
        """Patterns useful for nutrition domain."""
        return [
            {
                "source_domain": "fitness",
                "target_domain": "nutrition",
                "pattern_type": "training_nutrition",
                "content": "Protein timing around workouts matters for recovery"
            }
        ]

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """Fitness session start."""
        day = datetime.now().strftime("%A")
        day_de = {
            "Monday": "Montag",
            "Tuesday": "Dienstag",
            "Wednesday": "Mittwoch",
            "Thursday": "Donnerstag",
            "Friday": "Freitag",
            "Saturday": "Samstag",
            "Sunday": "Sonntag",
        }.get(day, day)

        return f"Heute ist {day_de}. Was steht an – Training, Recovery oder Planung?"

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """Fitness session end."""
        return "Reminder: Die beste Trainingseinheit ist die, die du machst. Nicht die perfekte."


# Singleton instance
fitness_domain = FitnessDomain()
