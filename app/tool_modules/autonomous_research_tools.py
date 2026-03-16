"""
Autonomous Research Tools - Proactive Background Research

Provides tools for:
- Scheduling automatic research
- Managing research priorities
- Analyzing insights
- User interest tracking
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.db_client import get_db_client

logger = logging.getLogger(__name__)


def run_autonomous_research(
    domain: Optional[str] = None,
    max_topics: int = 3,
    triggered_by: str = "manual",
    **kwargs
) -> Dict[str, Any]:
    """
    Execute autonomous research on high-priority topics.

    Args:
        domain: Specific domain to research (optional, all active if None)
        max_topics: Maximum topics to research per run
        triggered_by: Who/what triggered this (manual, scheduler, proactive)

    Returns:
        Dict with research results and insights
    """
    try:
        from app.services.research_service import ResearchService

        db = get_db_client()
        run_id = f"auto_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        # Get high-priority topics
        with db.get_cursor() as cur:
            if domain:
                cur.execute("""
                    SELECT t.id, t.name, t.query_template, d.name as domain_name, d.id as domain_id,
                           COALESCE(p.priority_score, 0.5) as priority,
                           p.last_researched_at
                    FROM research_topics t
                    JOIN research_domains d ON t.domain_id = d.id
                    LEFT JOIN research_topic_priorities p ON t.id = p.topic_id
                    WHERE t.is_active = TRUE AND d.is_active = TRUE
                    AND d.name = %s
                    ORDER BY COALESCE(p.priority_score, 0.5) DESC,
                             COALESCE(p.last_researched_at, '1970-01-01') ASC
                    LIMIT %s
                """, (domain, max_topics))
            else:
                cur.execute("""
                    SELECT t.id, t.name, t.query_template, d.name as domain_name, d.id as domain_id,
                           COALESCE(p.priority_score, 0.5) as priority,
                           p.last_researched_at
                    FROM research_topics t
                    JOIN research_domains d ON t.domain_id = d.id
                    LEFT JOIN research_topic_priorities p ON t.id = p.topic_id
                    WHERE t.is_active = TRUE AND d.is_active = TRUE
                    ORDER BY COALESCE(p.priority_score, 0.5) DESC,
                             COALESCE(p.last_researched_at, '1970-01-01') ASC
                    LIMIT %s
                """, (max_topics,))

            topics = cur.fetchall()

        if not topics:
            return {
                "success": True,
                "run_id": run_id,
                "message": "No active topics to research",
                "topics_processed": 0
            }

        # Create run record
        with db.get_cursor() as cur:
            cur.execute("""
                INSERT INTO research_runs
                (run_id, domain_id, triggered_by, status, started_at)
                VALUES (%s, %s, %s, 'running', NOW())
            """, (run_id, topics[0][4] if topics else None, triggered_by))

        # Execute research
        service = ResearchService()
        results = []
        insights = []
        errors = []

        for topic in topics:
            topic_id, topic_name, query_template, domain_name, domain_id, priority, last_researched = topic

            try:
                # Run research using existing service
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                asyncio.run,
                                service.run_research(domain_name, [topic_name])
                            )
                            session = future.result(timeout=120)
                    else:
                        session = loop.run_until_complete(
                            service.run_research(domain_name, [topic_name])
                        )
                except RuntimeError:
                    session = asyncio.run(
                        service.run_research(domain_name, [topic_name])
                    )

                # Extract insights from results
                if session and session.items_created > 0:
                    results.append({
                        "topic_id": topic_id,
                        "topic_name": topic_name,
                        "domain": domain_name,
                        "items_created": session.items_created,
                        "status": "success"
                    })

                    # Update topic priority (success increases score)
                    with db.get_cursor() as cur:
                        cur.execute("""
                            INSERT INTO research_topic_priorities
                            (topic_id, priority_score, last_researched_at, research_count, success_rate)
                            VALUES (%s, %s, NOW(), 1, 1.0)
                            ON CONFLICT (topic_id) DO UPDATE SET
                                last_researched_at = NOW(),
                                research_count = research_topic_priorities.research_count + 1,
                                success_rate = (research_topic_priorities.success_rate * research_topic_priorities.research_count + 1) /
                                              (research_topic_priorities.research_count + 1),
                                updated_at = NOW()
                        """, (topic_id, priority))

            except Exception as e:
                logger.error(f"Research failed for topic {topic_name}: {e}")
                errors.append({
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "error": str(e)
                })

        # Update run record
        with db.get_cursor() as cur:
            cur.execute("""
                UPDATE research_runs
                SET status = 'completed',
                    topics_processed = %s,
                    results_created = %s,
                    errors = %s,
                    completed_at = NOW()
                WHERE run_id = %s
            """, (
                len(topics),
                sum(r.get("items_created", 0) for r in results),
                str(errors) if errors else None,
                run_id
            ))

        return {
            "success": True,
            "run_id": run_id,
            "triggered_by": triggered_by,
            "topics_processed": len(topics),
            "results": results,
            "errors": errors if errors else None
        }

    except Exception as e:
        logger.error(f"Autonomous research failed: {e}")
        return {"success": False, "error": str(e)}


def get_research_schedule(
    domain: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get research schedule configuration.

    Args:
        domain: Filter by domain name (optional)

    Returns:
        Dict with schedule configurations
    """
    try:
        db = get_db_client()

        with db.get_cursor() as cur:
            if domain:
                cur.execute("""
                    SELECT s.id, d.name as domain, s.schedule_type, s.schedule_config,
                           s.max_topics_per_run, s.priority, s.is_enabled,
                           s.last_run_at, s.next_run_at
                    FROM research_schedule s
                    JOIN research_domains d ON s.domain_id = d.id
                    WHERE d.name = %s
                    ORDER BY s.priority DESC
                """, (domain,))
            else:
                cur.execute("""
                    SELECT s.id, d.name as domain, s.schedule_type, s.schedule_config,
                           s.max_topics_per_run, s.priority, s.is_enabled,
                           s.last_run_at, s.next_run_at
                    FROM research_schedule s
                    JOIN research_domains d ON s.domain_id = d.id
                    ORDER BY s.priority DESC
                """)

            schedules = cur.fetchall()

        return {
            "success": True,
            "schedules": [
                {
                    "id": s[0],
                    "domain": s[1],
                    "schedule_type": s[2],
                    "schedule_config": s[3],
                    "max_topics_per_run": s[4],
                    "priority": s[5],
                    "is_enabled": s[6],
                    "last_run_at": s[7].isoformat() if s[7] else None,
                    "next_run_at": s[8].isoformat() if s[8] else None
                }
                for s in schedules
            ]
        }

    except Exception as e:
        logger.error(f"Get schedule failed: {e}")
        return {"success": False, "error": str(e)}


def update_research_schedule(
    domain: str,
    is_enabled: Optional[bool] = None,
    schedule_type: Optional[str] = None,
    schedule_config: Optional[Dict] = None,
    max_topics_per_run: Optional[int] = None,
    priority: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Update research schedule for a domain.

    Args:
        domain: Domain name
        is_enabled: Enable/disable schedule
        schedule_type: daily, weekly, on_demand
        schedule_config: Schedule configuration (hour, minute, days)
        max_topics_per_run: Max topics per run
        priority: Schedule priority

    Returns:
        Dict with updated schedule
    """
    try:
        db = get_db_client()

        updates = []
        values = []

        if is_enabled is not None:
            updates.append("is_enabled = %s")
            values.append(is_enabled)
        if schedule_type:
            updates.append("schedule_type = %s")
            values.append(schedule_type)
        if schedule_config:
            updates.append("schedule_config = %s")
            values.append(str(schedule_config))
        if max_topics_per_run:
            updates.append("max_topics_per_run = %s")
            values.append(max_topics_per_run)
        if priority:
            updates.append("priority = %s")
            values.append(priority)

        if not updates:
            return {"success": False, "error": "No updates provided"}

        values.append(domain)

        with db.get_cursor() as cur:
            cur.execute(f"""
                UPDATE research_schedule s
                SET {", ".join(updates)}
                FROM research_domains d
                WHERE s.domain_id = d.id AND d.name = %s
                RETURNING s.id
            """, values)

            result = cur.fetchone()

        return {
            "success": result is not None,
            "domain": domain,
            "updated": result is not None
        }

    except Exception as e:
        logger.error(f"Update schedule failed: {e}")
        return {"success": False, "error": str(e)}


def get_research_insights(
    insight_type: Optional[str] = None,
    unnotified_only: bool = False,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get research insights.

    Args:
        insight_type: Filter by type (trend, opportunity, risk, news, learning)
        unnotified_only: Only return insights not yet notified
        limit: Max number of insights

    Returns:
        Dict with insights
    """
    try:
        db = get_db_client()

        conditions = []
        values = []

        if insight_type:
            conditions.append("insight_type = %s")
            values.append(insight_type)
        if unnotified_only:
            conditions.append("is_notified = FALSE")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.append(limit)

        with db.get_cursor() as cur:
            cur.execute(f"""
                SELECT id, run_id, topic_id, insight_type, title, summary,
                       confidence, relevance_score, source_urls, tags,
                       is_notified, is_actioned, created_at
                FROM research_insights
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
            """, values)

            insights = cur.fetchall()

        return {
            "success": True,
            "count": len(insights),
            "insights": [
                {
                    "id": i[0],
                    "run_id": i[1],
                    "topic_id": i[2],
                    "type": i[3],
                    "title": i[4],
                    "summary": i[5],
                    "confidence": i[6],
                    "relevance": i[7],
                    "sources": i[8],
                    "tags": i[9],
                    "notified": i[10],
                    "actioned": i[11],
                    "created_at": i[12].isoformat() if i[12] else None
                }
                for i in insights
            ]
        }

    except Exception as e:
        logger.error(f"Get insights failed: {e}")
        return {"success": False, "error": str(e)}


def mark_insight_notified(
    insight_id: int,
    **kwargs
) -> Dict[str, Any]:
    """
    Mark an insight as notified.

    Args:
        insight_id: Insight ID

    Returns:
        Dict with success status
    """
    try:
        db = get_db_client()

        with db.get_cursor() as cur:
            cur.execute("""
                UPDATE research_insights
                SET is_notified = TRUE
                WHERE id = %s
                RETURNING id
            """, (insight_id,))

            result = cur.fetchone()

        return {"success": result is not None}

    except Exception as e:
        return {"success": False, "error": str(e)}


def track_user_interest(
    topic: str,
    keywords: Optional[List[str]] = None,
    confidence: float = 0.7,
    **kwargs
) -> Dict[str, Any]:
    """
    Track a user interest for research prioritization.

    Args:
        topic: Interest topic
        keywords: Related keywords
        confidence: Confidence score (0-1)

    Returns:
        Dict with tracking result
    """
    try:
        db = get_db_client()

        with db.get_cursor() as cur:
            cur.execute("""
                INSERT INTO research_user_interests
                (interest_topic, interest_keywords, confidence, last_mentioned_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (interest_topic) DO UPDATE SET
                    mention_count = research_user_interests.mention_count + 1,
                    last_mentioned_at = NOW(),
                    confidence = GREATEST(research_user_interests.confidence, %s)
                RETURNING id, mention_count
            """, (topic, keywords, confidence, confidence))

            result = cur.fetchone()

        return {
            "success": True,
            "topic": topic,
            "id": result[0] if result else None,
            "mention_count": result[1] if result else 1
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_research_run_history(
    limit: int = 10,
    status: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get history of research runs.

    Args:
        limit: Max runs to return
        status: Filter by status (running, completed, failed)

    Returns:
        Dict with run history
    """
    try:
        db = get_db_client()

        conditions = []
        values = []

        if status:
            conditions.append("status = %s")
            values.append(status)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.append(limit)

        with db.get_cursor() as cur:
            cur.execute(f"""
                SELECT r.run_id, d.name as domain, r.triggered_by, r.status,
                       r.topics_processed, r.results_created, r.insights_generated,
                       r.started_at, r.completed_at
                FROM research_runs r
                LEFT JOIN research_domains d ON r.domain_id = d.id
                {where_clause}
                ORDER BY r.started_at DESC
                LIMIT %s
            """, values)

            runs = cur.fetchall()

        return {
            "success": True,
            "runs": [
                {
                    "run_id": r[0],
                    "domain": r[1],
                    "triggered_by": r[2],
                    "status": r[3],
                    "topics_processed": r[4],
                    "results_created": r[5],
                    "insights_generated": r[6],
                    "started_at": r[7].isoformat() if r[7] else None,
                    "completed_at": r[8].isoformat() if r[8] else None
                }
                for r in runs
            ]
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
AUTONOMOUS_RESEARCH_TOOLS = [
    {
        "name": "run_autonomous_research",
        "description": "Execute autonomous research on high-priority topics. Researches topics based on priority and recency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Specific domain to research (optional, researches all active domains if not specified)"
                },
                "max_topics": {
                    "type": "integer",
                    "description": "Maximum topics to research per run (default: 3)"
                },
                "triggered_by": {
                    "type": "string",
                    "enum": ["manual", "scheduler", "proactive"],
                    "description": "Who/what triggered this research"
                }
            }
        }
    },
    {
        "name": "get_research_schedule",
        "description": "Get research schedule configuration for domains.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter by domain name (optional)"
                }
            }
        }
    },
    {
        "name": "update_research_schedule",
        "description": "Update research schedule for a domain (enable/disable, change timing, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain name to update"
                },
                "is_enabled": {
                    "type": "boolean",
                    "description": "Enable or disable schedule"
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["daily", "weekly", "on_demand"],
                    "description": "Schedule type"
                },
                "schedule_config": {
                    "type": "object",
                    "description": "Schedule config (hour, minute, days)"
                },
                "max_topics_per_run": {
                    "type": "integer",
                    "description": "Max topics per run"
                }
            },
            "required": ["domain"]
        }
    },
    {
        "name": "get_research_insights",
        "description": "Get insights from research runs. Filter by type or notification status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "insight_type": {
                    "type": "string",
                    "enum": ["trend", "opportunity", "risk", "news", "learning"],
                    "description": "Filter by insight type"
                },
                "unnotified_only": {
                    "type": "boolean",
                    "description": "Only return insights not yet notified"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max insights to return (default: 20)"
                }
            }
        }
    },
    {
        "name": "track_user_interest",
        "description": "Track user interest for research prioritization. Helps prioritize what to research.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Interest topic"
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Related keywords"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0-1 (default: 0.7)"
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "get_research_run_history",
        "description": "Get history of research runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max runs to return (default: 10)"
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "completed", "failed"],
                    "description": "Filter by status"
                }
            }
        }
    }
]
