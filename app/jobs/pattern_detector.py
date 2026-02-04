#!/usr/bin/env python3
"""
Pattern Detection Job

Phase 16.4C: Daily pattern detection from timeline, feedback, and interactions.
Schedule: Daily 02:00 UTC via n8n or cron

Detects:
- Time-of-day patterns (when is user most active/focused)
- Feedback patterns (recurring themes in negative feedback)
- Interaction patterns (common query types, response quality trends)
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any
import json

from ..db_safety import safe_list_query, safe_write_query
from ..observability import get_logger

logger = get_logger("jarvis.pattern_detector")


def detect_patterns_daily(user_id: str = "micha", days_back: int = 30) -> List[Dict[str, Any]]:
    """
    Run pattern detection on recent data.

    Returns list of detected patterns.
    """
    patterns = []

    # 1. Time-of-day patterns from timeline
    time_patterns = detect_time_of_day_patterns(user_id, days_back)
    patterns.extend(time_patterns)

    # 2. Feedback theme patterns
    feedback_patterns = detect_feedback_themes(user_id, days_back)
    patterns.extend(feedback_patterns)

    # 3. Interaction quality trends
    quality_patterns = detect_quality_trends(user_id, days_back)
    patterns.extend(quality_patterns)

    # 4. Store detected patterns
    for pattern in patterns:
        store_pattern(user_id, pattern)

    logger.info(f"Pattern detection complete: {len(patterns)} patterns found")
    return patterns


def detect_time_of_day_patterns(user_id: str, days_back: int) -> List[Dict]:
    """Detect when user is most active based on timeline events."""
    patterns = []

    try:
        with safe_list_query('personal_timeline') as cur:
            cur.execute("""
                SELECT
                    EXTRACT(HOUR FROM created_at) as hour,
                    COUNT(*) as count
                FROM personal_timeline
                WHERE user_id = %s
                  AND created_at > NOW() - INTERVAL '%s days'
                GROUP BY EXTRACT(HOUR FROM created_at)
                ORDER BY count DESC
                LIMIT 3
            """, (user_id, days_back))

            rows = cur.fetchall()

            if rows and rows[0]['count'] >= 3:
                peak_hours = [int(r['hour']) for r in rows]
                total_events = sum(r['count'] for r in rows)

                patterns.append({
                    "pattern_type": "time_of_day_activity",
                    "description": f"Most active hours: {', '.join(f'{h}:00' for h in peak_hours)}",
                    "confidence": min(0.9, 0.3 + (total_events / 50)),  # More events = higher confidence
                    "evidence": [f"{r['count']} events at {int(r['hour'])}:00" for r in rows],
                    "data": {"peak_hours": peak_hours, "total_events": total_events}
                })

    except Exception as e:
        logger.error(f"Time pattern detection failed: {e}")

    return patterns


def detect_feedback_themes(user_id: str, days_back: int) -> List[Dict]:
    """Detect recurring themes in feedback tags."""
    patterns = []

    try:
        with safe_list_query('user_feedback') as cur:
            # Get tag frequency
            cur.execute("""
                SELECT
                    unnest(feedback_tags) as tag,
                    COUNT(*) as count
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND feedback_tags IS NOT NULL
                GROUP BY tag
                HAVING COUNT(*) >= 2
                ORDER BY count DESC
                LIMIT 5
            """, (days_back,))

            rows = cur.fetchall()

            if rows:
                top_tags = [(r['tag'], r['count']) for r in rows]

                patterns.append({
                    "pattern_type": "feedback_themes",
                    "description": f"Recurring feedback themes: {', '.join(t[0] for t in top_tags[:3])}",
                    "confidence": min(0.8, 0.4 + (len(rows) * 0.1)),
                    "evidence": [f"'{t[0]}' mentioned {t[1]}x" for t in top_tags],
                    "data": {"tags": dict(top_tags)}
                })

            # Check for negative pattern
            cur.execute("""
                SELECT COUNT(*) as neg_count
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND (rating < 3 OR thumbs_up = false)
            """, (days_back,))

            neg_row = cur.fetchone()
            neg_count = neg_row['neg_count'] or 0

            if neg_count >= 5:
                patterns.append({
                    "pattern_type": "negative_feedback_trend",
                    "description": f"Elevated negative feedback: {neg_count} in {days_back} days",
                    "confidence": min(0.85, 0.5 + (neg_count / 20)),
                    "evidence": [f"{neg_count} negative feedback instances"],
                    "data": {"negative_count": neg_count, "period_days": days_back}
                })

    except Exception as e:
        logger.error(f"Feedback theme detection failed: {e}")

    return patterns


def detect_quality_trends(user_id: str, days_back: int) -> List[Dict]:
    """Detect interaction quality trends."""
    patterns = []

    try:
        with safe_list_query('interaction_quality') as cur:
            # Get average satisfaction over time
            cur.execute("""
                SELECT
                    DATE(timestamp) as date,
                    AVG(inferred_satisfaction) as avg_satisfaction,
                    COUNT(*) as count
                FROM interaction_quality
                WHERE timestamp > NOW() - INTERVAL '%s days'
                GROUP BY DATE(timestamp)
                HAVING COUNT(*) >= 2
                ORDER BY date
            """, (days_back,))

            rows = cur.fetchall()

            if len(rows) >= 3:
                # Calculate trend
                satisfactions = [float(r['avg_satisfaction']) for r in rows if r['avg_satisfaction']]

                if satisfactions:
                    first_half = sum(satisfactions[:len(satisfactions)//2]) / max(1, len(satisfactions)//2)
                    second_half = sum(satisfactions[len(satisfactions)//2:]) / max(1, len(satisfactions) - len(satisfactions)//2)

                    trend = "improving" if second_half > first_half + 0.05 else "declining" if second_half < first_half - 0.05 else "stable"

                    patterns.append({
                        "pattern_type": "quality_trend",
                        "description": f"Interaction quality is {trend} (avg: {sum(satisfactions)/len(satisfactions):.2f})",
                        "confidence": min(0.75, 0.4 + (len(rows) * 0.05)),
                        "evidence": [f"Based on {sum(r['count'] for r in rows)} interactions over {len(rows)} days"],
                        "data": {"trend": trend, "first_half_avg": first_half, "second_half_avg": second_half}
                    })

    except Exception as e:
        logger.error(f"Quality trend detection failed: {e}")

    return patterns


def store_pattern(user_id: str, pattern: Dict) -> bool:
    """Store detected pattern in database."""
    try:
        with safe_write_query('detected_patterns') as cur:
            cur.execute("""
                INSERT INTO detected_patterns (
                    user_id, pattern_type, pattern_name, description,
                    pattern_data, confidence, time_scope,
                    observation_count, last_matched_at, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), true)
                ON CONFLICT (user_id, pattern_type)
                DO UPDATE SET
                    description = EXCLUDED.description,
                    pattern_data = EXCLUDED.pattern_data,
                    confidence = GREATEST(detected_patterns.confidence, EXCLUDED.confidence),
                    observation_count = detected_patterns.observation_count + 1,
                    last_matched_at = NOW(),
                    updated_at = NOW()
            """, (
                user_id,
                pattern['pattern_type'],
                pattern['pattern_type'],  # pattern_name = pattern_type for now
                pattern['description'],
                json.dumps(pattern.get('data', {})),
                pattern['confidence'],
                'daily',
                1
            ))
            return True

    except Exception as e:
        logger.error(f"Failed to store pattern: {e}")
        return False


def run_job():
    """Main entry point for scheduled job."""
    logger.info("Starting daily pattern detection job")

    try:
        patterns = detect_patterns_daily()

        # Log summary
        summary = {
            "patterns_detected": len(patterns),
            "pattern_types": [p['pattern_type'] for p in patterns],
            "timestamp": datetime.utcnow().isoformat()
        }

        logger.info(f"Pattern detection complete: {json.dumps(summary)}")

        return {"status": "success", "patterns": len(patterns)}

    except Exception as e:
        logger.error(f"Pattern detection job failed: {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    # Run directly for testing
    result = run_job()
    print(json.dumps(result, indent=2))
