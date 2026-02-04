"""
Work Coaching Domain

Specialized coaching for:
- Project management
- Career development
- Skill building
- Stakeholder management
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from . import BaseDomain, DomainContext


class WorkDomain(BaseDomain):
    """Work and career coaching domain."""

    @property
    def domain_id(self) -> str:
        return "work"

    @property
    def name(self) -> str:
        return "Work Coach"

    def build_context(self, ctx: DomainContext) -> str:
        """Build work-specific context."""
        context_parts = [
            "=== WORK COACHING MODE ===",
            "",
            "Du bist ein Work/Karriere Coach für Projekte, Skills und Stakeholder.",
            "",
        ]

        # Add user work profile
        if ctx.user_profile:
            role = ctx.user_profile.get("current_role", "")
            company = ctx.user_profile.get("company", "")
            goals = ctx.user_profile.get("career_goals", [])
            skills = ctx.user_profile.get("skills_developing", [])

            if role:
                context_parts.append(f"Rolle: {role}")
            if company:
                context_parts.append(f"Unternehmen: {company}")
            if goals:
                context_parts.append(f"Karriereziele: {', '.join(goals)}")
            if skills:
                context_parts.append(f"Skills in Entwicklung: {', '.join(skills)}")
            context_parts.append("")

        context_parts.extend([
            "## Projekt-Analyse Format",
            "```",
            "**Projekt:** [Name]",
            "**Status:** 🟢/🟡/🔴",
            "",
            "**Blockers:**",
            "- [Blocker 1]: [Lösungsansatz]",
            "",
            "**Nächste Schritte (diese Woche):**",
            "1. [ ] [Action + Owner]",
            "2. [ ] [Action + Owner]",
            "",
            "**Stakeholder-Update nötig:** [Ja/Nein + wem]",
            "```",
            "",
            "## Stakeholder Matrix",
            "| Stakeholder | Interest | Power | Strategy |",
            "|-------------|----------|-------|----------|",
            "| [Name] | High/Low | High/Low | Manage closely / Keep informed |",
            "",
            "## Skill Development (70-20-10)",
            "- 70% Learning on the job",
            "- 20% Learning from others",
            "- 10% Formal training",
            "",
            "## Prioritization (Eisenhower)",
            "| | Urgent | Not Urgent |",
            "|---|--------|------------|",
            "| Important | DO | SCHEDULE |",
            "| Not Important | DELEGATE | ELIMINATE |",
        ])

        return "\n".join(context_parts)

    def get_tools(self, ctx: DomainContext) -> List[str]:
        """Work uses email, chat search and calendar."""
        return ["search_emails", "search_chats", "calendar_today", "web_search"]

    def extract_insights(self, message: str, response: str) -> List[Dict[str, Any]]:
        """Extract work-related insights."""
        insights = []
        message_lower = message.lower()

        # Track project mentions
        project_keywords = ["projekt", "project", "initiative", "launch", "rollout"]
        for keyword in project_keywords:
            if keyword in message_lower:
                insights.append({
                    "type": "project_mention",
                    "keyword": keyword,
                    "timestamp": datetime.utcnow().isoformat()
                })
                break

        # Track challenge types
        challenges = {
            "blocker": "blocker",
            "stakeholder": "stakeholder",
            "deadline": "timeline",
            "resource": "resources",
            "skill": "skills",
            "politik": "politics",
        }

        for keyword, challenge_type in challenges.items():
            if keyword in message_lower:
                insights.append({
                    "type": "work_challenge",
                    "challenge": challenge_type,
                    "timestamp": datetime.utcnow().isoformat()
                })

        return insights

    def get_cross_domain_patterns(self, ctx: DomainContext) -> List[Dict[str, Any]]:
        """Patterns useful for communication domain."""
        return [
            {
                "source_domain": "work",
                "target_domain": "communication",
                "pattern_type": "stakeholder_communication",
                "content": "Stakeholder issues often need communication coaching"
            }
        ]

    def on_session_start(self, ctx: DomainContext) -> Optional[str]:
        """Work session start."""
        day = datetime.now().weekday()
        if day == 0:
            return "Montag = Wochenplanung. Was sind die Top 3 Prioritäten?"
        elif day == 4:
            return "Freitag = Review. Was lief gut, was nicht?"
        else:
            return "Was ist der wichtigste Blocker oder die größte Priorität?"

    def on_session_end(self, ctx: DomainContext) -> Optional[str]:
        """Work session end."""
        return "Nächster Schritt klar? Wenn nicht, frag nochmal."


# Singleton instance
work_domain = WorkDomain()
