"""
Jarvis Consolidation Module
Nightly "sleep-like" consolidation of evidence into knowledge proposals.

Collects new evidence since last consolidation, identifies patterns,
and generates knowledge proposals for human review (HITL).
"""
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import Counter

from .observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.consolidation")


def get_last_consolidation_ts(namespace: str) -> Optional[datetime]:
    """Get timestamp of last successful consolidation for namespace"""
    from . import state_db

    conn = state_db._get_conn()
    cursor = conn.execute("""
        SELECT MAX(ingest_ts) as last_ts
        FROM ingest_log
        WHERE namespace = ? AND ingest_type = 'consolidation' AND status = 'success'
    """, (namespace,))
    row = cursor.fetchone()
    conn.close()

    if row and row["last_ts"]:
        return datetime.fromisoformat(row["last_ts"])
    return None


def get_new_evidence_since(namespace: str, since_ts: Optional[datetime], days: int = 7) -> List[Dict]:
    """Get evidence ingested since last consolidation (or last N days)"""
    from . import state_db

    if since_ts is None:
        since_ts = datetime.now() - timedelta(days=days)

    conn = state_db._get_conn()
    cursor = conn.execute("""
        SELECT source_path, ingest_type, ingest_ts, chunks_upserted
        FROM ingest_log
        WHERE namespace = ?
        AND status = 'success'
        AND ingest_type != 'consolidation'
        AND datetime(ingest_ts) > datetime(?)
        ORDER BY ingest_ts DESC
    """, (namespace, since_ts.isoformat()))

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    log_with_context(logger, "info", "Found new evidence",
                    namespace=namespace, count=len(results), since=since_ts.isoformat())
    return results


def extract_person_mentions(namespace: str, days: int = 7) -> Dict[str, int]:
    """Extract person mentions from recent conversations and emails"""
    from . import knowledge_db

    # Get known person IDs for matching
    known_persons = {}
    try:
        people = knowledge_db.get_all_people()
        for p in people:
            name_lower = p.get("name", "").lower()
            person_id = p.get("person_id", "")
            if name_lower and person_id:
                known_persons[name_lower] = person_id
                # Also add first name
                first_name = name_lower.split()[0] if " " in name_lower else None
                if first_name and len(first_name) > 2:
                    known_persons[first_name] = person_id
    except Exception as e:
        log_with_context(logger, "warning", "Could not load known persons", error=str(e))

    # Count mentions from topic_mentions table
    from . import session_manager

    mention_counts = Counter()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        with session_manager._get_conn() as conn:
            cursor = conn.execute("""
                SELECT topic, SUM(mention_count) as total
                FROM topic_mentions
                WHERE datetime(last_mentioned) > datetime(?)
                GROUP BY topic
            """, (cutoff.isoformat(),))

            for row in cursor.fetchall():
                topic_lower = row["topic"].lower()
                # Check if topic matches a known person
                if topic_lower in known_persons:
                    mention_counts[known_persons[topic_lower]] += row["total"]
    except Exception as e:
        log_with_context(logger, "warning", "Could not extract person mentions", error=str(e))

    return dict(mention_counts)


def extract_recurring_topics(namespace: str, days: int = 7, min_mentions: int = 2) -> List[Dict]:
    """Find topics mentioned multiple times (potential knowledge candidates)"""
    from . import pattern_detector

    try:
        patterns = pattern_detector.detect_recurring_topics(
            min_count=min_mentions,
            days=days
        )
        # Convert Pattern objects to dicts
        return [
            {
                "topic": p.evidence.get("topic", "unknown") if isinstance(p.evidence, dict) else "unknown",
                "mention_count": p.occurrences,
                "session_ids": []
            }
            for p in patterns
            if p.actionable  # Only include actionable patterns
        ]
    except Exception as e:
        log_with_context(logger, "warning", "Could not extract recurring topics", error=str(e))
        return []


def generate_person_insights(person_mentions: Dict[str, int], min_mentions: int = 3) -> List[Dict]:
    """Generate insight proposals for frequently mentioned people"""
    from . import knowledge_db

    insights = []

    for person_id, count in person_mentions.items():
        if count < min_mentions:
            continue

        # Check if person exists
        profile = knowledge_db.get_person_profile(person_id)
        if not profile:
            continue

        # Generate insight about frequency
        insight = {
            "insight_type": "communication_pattern",
            "subject_type": "person",
            "subject_id": person_id,
            "insight_text": f"{profile.get('name', person_id)} wurde {count}x in den letzten Tagen erwaehnt. Moeglicherweise ist diese Person gerade besonders relevant.",
            "confidence": "medium" if count < 5 else "high",
            "evidence_sources": [{
                "type": "topic_mentions",
                "count": count,
                "period_days": 7
            }]
        }
        insights.append(insight)

    return insights


def generate_topic_insights(recurring_topics: List[Dict]) -> List[Dict]:
    """Generate insight proposals for recurring topics"""
    insights = []

    for topic in recurring_topics:
        if topic.get("mention_count", 0) < 3:
            continue

        insight = {
            "insight_type": "recurring_topic",
            "subject_type": "topic",
            "subject_id": topic.get("topic", "unknown"),
            "insight_text": f"Thema '{topic.get('topic')}' wurde {topic.get('mention_count')}x erwaehnt. Moeglicherweise ein aktives Projekt oder wiederkehrendes Anliegen.",
            "confidence": "medium",
            "evidence_sources": [{
                "type": "topic_analysis",
                "mention_count": topic.get("mention_count"),
                "sessions": topic.get("session_ids", [])
            }]
        }
        insights.append(insight)

    return insights


def submit_proposals_to_review(insights: List[Dict], namespace: str) -> List[int]:
    """Submit generated insights to the review queue"""
    from . import knowledge_db

    queue_ids = []

    for insight in insights:
        try:
            # Create the insight (status=proposed)
            insight_id = knowledge_db.propose_insight(
                insight_type=insight["insight_type"],
                subject_type=insight["subject_type"],
                subject_id=insight["subject_id"],
                insight_text=insight["insight_text"],
                confidence=insight.get("confidence", "medium"),
                evidence_sources=insight.get("evidence_sources", []),
                proposed_by="consolidation_job"
            )

            if insight_id:
                queue_ids.append(insight_id)
                log_with_context(logger, "info", "Created insight proposal",
                               insight_id=insight_id, type=insight["insight_type"])
        except Exception as e:
            log_with_context(logger, "error", "Failed to create insight proposal",
                           insight=insight, error=str(e))

    return queue_ids


def record_consolidation_run(namespace: str, status: str, proposals_created: int):
    """Record consolidation run in ingest_log"""
    from . import state_db

    state_db.record_ingest(
        source_path=f"consolidation/{namespace}/{datetime.now().strftime('%Y%m%d')}",
        namespace=namespace,
        ingest_type="consolidation",
        ingest_ts=datetime.now().isoformat(),
        chunks_upserted=proposals_created,
        status=status
    )


def run_consolidation(
    namespace: str,
    days: int = 7,
    min_person_mentions: int = 3,
    min_topic_mentions: int = 2,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Run consolidation for a namespace.

    1. Collect new evidence since last consolidation
    2. Extract patterns (person mentions, recurring topics)
    3. Generate knowledge proposals
    4. Submit to review queue (unless dry_run)

    Returns summary of what was found/proposed.
    """
    start_time = datetime.now()
    metrics.inc("consolidation_runs")

    log_with_context(logger, "info", "Starting consolidation",
                    namespace=namespace, days=days, dry_run=dry_run)

    result = {
        "namespace": namespace,
        "days": days,
        "dry_run": dry_run,
        "started_at": start_time.isoformat(),
        "new_evidence_count": 0,
        "person_mentions": {},
        "recurring_topics": [],
        "insights_generated": [],
        "proposals_created": 0,
        "review_queue_ids": [],
        "status": "success"
    }

    try:
        # 1. Get last consolidation timestamp
        last_consolidation = get_last_consolidation_ts(namespace)
        result["last_consolidation"] = last_consolidation.isoformat() if last_consolidation else None

        # 2. Get new evidence
        new_evidence = get_new_evidence_since(namespace, last_consolidation, days)
        result["new_evidence_count"] = len(new_evidence)

        if len(new_evidence) == 0:
            log_with_context(logger, "info", "No new evidence to consolidate", namespace=namespace)
            result["message"] = "No new evidence since last consolidation"
            return result

        # 3. Extract patterns
        person_mentions = extract_person_mentions(namespace, days)
        result["person_mentions"] = person_mentions

        recurring_topics = extract_recurring_topics(namespace, days, min_topic_mentions)
        result["recurring_topics"] = recurring_topics

        # 4. Generate insights
        insights = []
        insights.extend(generate_person_insights(person_mentions, min_person_mentions))
        insights.extend(generate_topic_insights(recurring_topics))
        result["insights_generated"] = insights

        # 5. Submit to review queue (unless dry_run)
        if not dry_run and insights:
            queue_ids = submit_proposals_to_review(insights, namespace)
            result["proposals_created"] = len(queue_ids)
            result["review_queue_ids"] = queue_ids

            # Record successful run
            record_consolidation_run(namespace, "success", len(queue_ids))
        elif dry_run:
            result["message"] = "Dry run - no proposals created"
        else:
            result["message"] = "No insights generated"
            record_consolidation_run(namespace, "success", 0)

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        result["duration_ms"] = round(duration_ms, 1)
        metrics.timing("consolidation_duration_ms", duration_ms)

        log_with_context(logger, "info", "Consolidation completed",
                        namespace=namespace,
                        evidence=len(new_evidence),
                        insights=len(insights),
                        proposals=result["proposals_created"])

    except Exception as e:
        log_with_context(logger, "error", "Consolidation failed",
                        namespace=namespace, error=str(e))
        result["status"] = "error"
        result["error"] = str(e)
        metrics.inc("consolidation_errors")

        # Record failed run
        if not dry_run:
            record_consolidation_run(namespace, "error", 0)

    return result


def get_consolidation_stats() -> Dict[str, Any]:
    """Get consolidation statistics for all namespaces"""
    from . import state_db

    stats = {
        "namespaces": {},
        "total_runs": 0,
        "total_proposals": 0
    }

    try:
        conn = state_db._get_conn()

        # Get last consolidation per namespace
        cursor = conn.execute("""
            SELECT namespace,
                   MAX(ingest_ts) as last_consolidation,
                   COUNT(*) as run_count,
                   SUM(chunks_upserted) as total_proposals
            FROM ingest_log
            WHERE ingest_type = 'consolidation'
            GROUP BY namespace
        """)

        for row in cursor.fetchall():
            stats["namespaces"][row["namespace"]] = {
                "last_consolidation": row["last_consolidation"],
                "run_count": row["run_count"],
                "total_proposals": row["total_proposals"] or 0
            }
            stats["total_runs"] += row["run_count"]
            stats["total_proposals"] += row["total_proposals"] or 0

        conn.close()

    except Exception as e:
        log_with_context(logger, "error", "Failed to get consolidation stats", error=str(e))

    return stats
