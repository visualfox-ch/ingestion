"""
Autonomous Research Job - Scheduled Background Research

Phase 2B: Proactive Background Work
Runs daily to:
1. Select high-priority research topics
2. Execute research using multi-provider pipeline
3. Extract and store insights
4. Notify user of important findings
"""

import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.autonomous_research")

# Configuration
MAX_TOPICS_DEFAULT = int(os.getenv("JARVIS_AUTO_RESEARCH_MAX_TOPICS", "3"))
RESEARCH_TIMEOUT = 120  # seconds per topic


@dataclass
class ResearchRunResult:
    """Result of a research run."""
    run_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    topics_processed: int = 0
    insights_generated: int = 0
    errors: List[Dict] = field(default_factory=list)
    status: str = "pending"


class AutonomousResearchRunner:
    """Executes autonomous background research."""

    def __init__(self):
        self.result: Optional[ResearchRunResult] = None

    def run(self, max_topics: int = None, domain: str = None) -> Dict[str, Any]:
        """
        Run autonomous research.

        Args:
            max_topics: Max topics to research (default from env)
            domain: Specific domain to research (optional)

        Returns:
            Dict with run results
        """
        import uuid

        max_topics = max_topics or MAX_TOPICS_DEFAULT
        run_id = f"scheduled_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        self.result = ResearchRunResult(
            run_id=run_id,
            started_at=datetime.utcnow()
        )

        log_with_context(logger, "info", "Starting autonomous research",
                        run_id=run_id, max_topics=max_topics, domain=domain)

        try:
            # Use the autonomous research tool
            from ..tool_modules.autonomous_research_tools import run_autonomous_research

            result = run_autonomous_research(
                domain=domain,
                max_topics=max_topics,
                triggered_by="scheduler"
            )

            self.result.completed_at = datetime.utcnow()
            self.result.status = "completed" if result.get("success") else "failed"
            self.result.topics_processed = result.get("topics_processed", 0)

            if result.get("errors"):
                self.result.errors = result["errors"]

            # Extract insights from results
            insights_count = self._extract_insights(result)
            self.result.insights_generated = insights_count

            # Notify if important insights found
            if insights_count > 0:
                self._notify_insights(insights_count)

            return self._build_summary(result)

        except Exception as e:
            logger.error(f"Autonomous research failed: {e}")
            self.result.status = "error"
            self.result.completed_at = datetime.utcnow()
            self.result.errors.append({"error": str(e)})

            return {
                "success": False,
                "run_id": run_id,
                "error": str(e)
            }

    def _extract_insights(self, result: Dict) -> int:
        """Extract and store insights from research results."""
        insights_count = 0

        try:
            from ..db_client import get_db_client

            db = get_db_client()
            results = result.get("results", [])

            for r in results:
                # Each successful research might contain insights
                # For now, count items created as potential insights
                insights_count += r.get("items_created", 0)

            # TODO: Analyze results with LLM to extract actionable insights
            # This would identify trends, opportunities, risks from the research

        except Exception as e:
            logger.warning(f"Insight extraction failed: {e}")

        return insights_count

    def _notify_insights(self, count: int):
        """Notify user of important insights via Telegram."""
        try:
            import requests

            telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
            allowed_users = os.getenv("TELEGRAM_ALLOWED_USERS", "")

            if not telegram_token or not allowed_users:
                logger.debug("Telegram not configured, skipping notification")
                return

            user_id = allowed_users.split(",")[0].strip()
            if not user_id:
                return

            message = (
                f"Research Update\n\n"
                f"Autonomous research completed with {count} new findings.\n"
                f"Use /research_insights to review."
            )

            requests.post(
                f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": message
                },
                timeout=10
            )

        except Exception as e:
            logger.warning(f"Insight notification failed: {e}")

    def _build_summary(self, result: Dict) -> Dict[str, Any]:
        """Build run summary."""
        duration = None
        if self.result.completed_at and self.result.started_at:
            duration = (self.result.completed_at - self.result.started_at).total_seconds()

        return {
            "success": result.get("success", False),
            "run_id": self.result.run_id,
            "status": self.result.status,
            "topics_processed": self.result.topics_processed,
            "insights_generated": self.result.insights_generated,
            "duration_seconds": duration,
            "errors": self.result.errors if self.result.errors else None,
            "timestamp": self.result.started_at.isoformat()
        }


def run_autonomous_research_job(
    max_topics: int = None,
    domain: str = None
) -> Dict[str, Any]:
    """
    Entry point for scheduled autonomous research.

    Called by APScheduler from scheduler.py.
    """
    runner = AutonomousResearchRunner()
    return runner.run(max_topics=max_topics, domain=domain)


def check_research_due() -> bool:
    """
    Check if any domain is due for research.

    Used by proactive system to trigger research outside schedule.
    """
    try:
        from ..db_client import get_db_client

        db = get_db_client()

        with db.get_cursor() as cur:
            # Check for topics not researched in last 24 hours with high priority
            cur.execute("""
                SELECT COUNT(*) FROM research_topic_priorities
                WHERE (last_researched_at IS NULL
                       OR last_researched_at < NOW() - INTERVAL '24 hours')
                AND priority_score > 0.7
            """)
            count = cur.fetchone()[0]

        return count > 0

    except Exception as e:
        logger.warning(f"Research due check failed: {e}")
        return False


def get_next_research_topics(limit: int = 5) -> List[Dict]:
    """
    Get the next topics to research based on priority.

    Useful for showing what would be researched next.
    """
    try:
        from ..db_client import get_db_client

        db = get_db_client()

        with db.get_cursor() as cur:
            cur.execute("""
                SELECT t.name, d.name as domain,
                       COALESCE(p.priority_score, 0.5) as priority,
                       p.last_researched_at
                FROM research_topics t
                JOIN research_domains d ON t.domain_id = d.id
                LEFT JOIN research_topic_priorities p ON t.id = p.topic_id
                WHERE t.is_active = TRUE AND d.is_active = TRUE
                ORDER BY COALESCE(p.priority_score, 0.5) DESC,
                         COALESCE(p.last_researched_at, '1970-01-01') ASC
                LIMIT %s
            """, (limit,))

            topics = cur.fetchall()

        return [
            {
                "topic": t[0],
                "domain": t[1],
                "priority": t[2],
                "last_researched": t[3].isoformat() if t[3] else None
            }
            for t in topics
        ]

    except Exception as e:
        logger.warning(f"Get next topics failed: {e}")
        return []
