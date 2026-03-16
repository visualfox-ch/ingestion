"""
Pattern Recognition Service - Phase 3.3

Statistical pattern recognition for queries and sessions:
- Clusters similar queries
- Identifies usage patterns
- Predicts outcomes based on history
- Finds anomalies in usage
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import json
import hashlib
import math

from ..postgres_state import get_cursor

logger = logging.getLogger(__name__)

# Pattern types
PATTERN_TYPES = [
    'temporal',      # Time-based patterns
    'sequential',    # Tool sequence patterns
    'categorical',   # Category co-occurrence
    'behavioral',    # User behavior patterns
    'contextual'     # Context-based patterns
]


class PatternRecognitionService:
    """
    Recognizes patterns in query and tool usage data.

    Uses statistical methods to find meaningful patterns
    that can improve prediction and personalization.
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure pattern tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS recognized_patterns (
                        id SERIAL PRIMARY KEY,
                        pattern_id VARCHAR(64) UNIQUE NOT NULL,
                        pattern_type VARCHAR(50) NOT NULL,
                        pattern_name VARCHAR(200) NOT NULL,
                        pattern_data JSONB NOT NULL,
                        confidence FLOAT DEFAULT 0.5,
                        occurrence_count INTEGER DEFAULT 1,
                        last_seen_at TIMESTAMP DEFAULT NOW(),
                        created_at TIMESTAMP DEFAULT NOW(),
                        is_active BOOLEAN DEFAULT true
                    );

                    CREATE INDEX IF NOT EXISTS idx_patterns_type
                        ON recognized_patterns(pattern_type);
                    CREATE INDEX IF NOT EXISTS idx_patterns_confidence
                        ON recognized_patterns(confidence DESC);

                    CREATE TABLE IF NOT EXISTS query_clusters (
                        id SERIAL PRIMARY KEY,
                        cluster_id VARCHAR(64) UNIQUE NOT NULL,
                        cluster_name VARCHAR(200),
                        centroid_keywords JSONB NOT NULL,
                        member_count INTEGER DEFAULT 0,
                        avg_success_rate FLOAT,
                        common_tools JSONB DEFAULT '[]'::jsonb,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_clusters_members
                        ON query_clusters(member_count DESC);

                    CREATE TABLE IF NOT EXISTS pattern_predictions (
                        id SERIAL PRIMARY KEY,
                        prediction_type VARCHAR(50) NOT NULL,
                        input_signature JSONB NOT NULL,
                        predicted_value VARCHAR(200),
                        confidence FLOAT,
                        was_correct BOOLEAN,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_predictions_type
                        ON pattern_predictions(prediction_type);
                    CREATE INDEX IF NOT EXISTS idx_predictions_created
                        ON pattern_predictions(created_at DESC);

                    CREATE TABLE IF NOT EXISTS usage_anomalies (
                        id SERIAL PRIMARY KEY,
                        anomaly_type VARCHAR(50) NOT NULL,
                        description TEXT NOT NULL,
                        severity VARCHAR(20) DEFAULT 'low',
                        context_data JSONB,
                        is_resolved BOOLEAN DEFAULT false,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_anomalies_type
                        ON usage_anomalies(anomaly_type);
                    CREATE INDEX IF NOT EXISTS idx_anomalies_resolved
                        ON usage_anomalies(is_resolved, created_at DESC);
                """)
        except Exception as e:
            logger.debug(f"Tables may already exist: {e}")

    def analyze_temporal_patterns(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze time-based usage patterns.

        Finds patterns like "most active hours", "weekend vs weekday", etc.
        """
        try:
            with get_cursor() as cur:
                # Hourly distribution
                cur.execute("""
                    SELECT
                        EXTRACT(HOUR FROM created_at) as hour,
                        COUNT(*) as count
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    GROUP BY EXTRACT(HOUR FROM created_at)
                    ORDER BY hour
                """, (days,))

                hourly = {int(row['hour']): row['count'] for row in cur.fetchall()}

                # Day of week distribution
                cur.execute("""
                    SELECT
                        EXTRACT(DOW FROM created_at) as dow,
                        COUNT(*) as count
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    GROUP BY EXTRACT(DOW FROM created_at)
                    ORDER BY dow
                """, (days,))

                day_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
                daily = {day_names[int(row['dow'])]: row['count'] for row in cur.fetchall()}

                # Find peak hours
                if hourly:
                    total = sum(hourly.values())
                    peak_hour = max(hourly, key=hourly.get)
                    peak_pct = round(hourly[peak_hour] / total * 100, 1) if total > 0 else 0

                    # Morning (6-12), Afternoon (12-18), Evening (18-22), Night (22-6)
                    periods = {
                        'morning': sum(hourly.get(h, 0) for h in range(6, 12)),
                        'afternoon': sum(hourly.get(h, 0) for h in range(12, 18)),
                        'evening': sum(hourly.get(h, 0) for h in range(18, 22)),
                        'night': sum(hourly.get(h, 0) for h in list(range(22, 24)) + list(range(0, 6)))
                    }

                    # Save temporal pattern
                    pattern_data = {
                        "peak_hour": peak_hour,
                        "peak_percentage": peak_pct,
                        "periods": periods,
                        "most_active_period": max(periods, key=periods.get)
                    }

                    self._save_pattern(
                        cur,
                        "temporal",
                        "daily_activity",
                        pattern_data,
                        0.8
                    )

                return {
                    "success": True,
                    "period_days": days,
                    "hourly_distribution": hourly,
                    "daily_distribution": daily,
                    "patterns": {
                        "peak_hour": peak_hour if hourly else None,
                        "most_active_day": max(daily, key=daily.get) if daily else None,
                        "periods": periods if hourly else {}
                    }
                }

        except Exception as e:
            logger.error(f"Analyze temporal patterns failed: {e}")
            return {"success": False, "error": str(e)}

    def analyze_tool_cooccurrence(
        self,
        days: int = 30,
        window_minutes: int = 10
    ) -> Dict[str, Any]:
        """
        Analyze which tools are commonly used together.

        Finds co-occurrence patterns within a time window.
        """
        try:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT tool_name, created_at
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    ORDER BY created_at
                """, (days,))

                rows = cur.fetchall()

                # Build co-occurrence matrix
                cooccurrence = defaultdict(lambda: defaultdict(int))
                tool_counts = defaultdict(int)

                for i, row in enumerate(rows):
                    tool1 = row['tool_name']
                    tool_counts[tool1] += 1
                    time1 = row['created_at']

                    # Look at nearby tools
                    for j in range(i + 1, min(i + 20, len(rows))):
                        tool2 = rows[j]['tool_name']
                        time2 = rows[j]['created_at']

                        if (time2 - time1).total_seconds() > window_minutes * 60:
                            break

                        if tool1 != tool2:
                            cooccurrence[tool1][tool2] += 1
                            cooccurrence[tool2][tool1] += 1

                # Find strongest pairs
                pairs = []
                seen = set()
                for tool1, others in cooccurrence.items():
                    for tool2, count in others.items():
                        pair_key = tuple(sorted([tool1, tool2]))
                        if pair_key not in seen and count >= 3:
                            seen.add(pair_key)
                            # Calculate lift (co-occurrence vs expected)
                            expected = (tool_counts[tool1] * tool_counts[tool2]) / len(rows) if rows else 1
                            lift = count / expected if expected > 0 else 0
                            pairs.append({
                                "tools": list(pair_key),
                                "count": count,
                                "lift": round(lift, 2)
                            })

                pairs.sort(key=lambda x: x['lift'], reverse=True)

                # Save top co-occurrence patterns
                for pair in pairs[:10]:
                    self._save_pattern(
                        cur,
                        "sequential",
                        f"cooccur_{pair['tools'][0]}_{pair['tools'][1]}",
                        pair,
                        min(0.9, pair['lift'] / 5)  # Normalize lift to confidence
                    )

                return {
                    "success": True,
                    "period_days": days,
                    "window_minutes": window_minutes,
                    "total_tools": len(tool_counts),
                    "top_pairs": pairs[:20],
                    "tool_frequencies": dict(sorted(
                        tool_counts.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )[:15])
                }

        except Exception as e:
            logger.error(f"Analyze tool cooccurrence failed: {e}")
            return {"success": False, "error": str(e)}

    def cluster_queries(
        self,
        days: int = 30,
        min_cluster_size: int = 3
    ) -> Dict[str, Any]:
        """
        Cluster similar queries based on keywords and outcomes.

        Groups queries with similar patterns for better prediction.
        """
        try:
            with get_cursor() as cur:
                # Get recent queries with their tool outcomes
                cur.execute("""
                    SELECT tool_input, tool_name, success
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    AND tool_input IS NOT NULL
                """, (days,))

                # Extract query keywords
                query_data = []
                for row in cur.fetchall():
                    tool_input = row['tool_input']
                    query = tool_input.get('query', '') or tool_input.get('question', '') or ''
                    if query:
                        keywords = self._extract_keywords(query.lower())
                        if keywords:
                            query_data.append({
                                "keywords": keywords,
                                "tool": row['tool_name'],
                                "success": row['success']
                            })

                # Simple keyword-based clustering
                clusters = defaultdict(list)
                for qd in query_data:
                    # Use top 3 keywords as cluster key
                    key = tuple(sorted(qd['keywords'][:3]))
                    clusters[key].append(qd)

                # Filter and save clusters
                valid_clusters = []
                for key, members in clusters.items():
                    if len(members) >= min_cluster_size:
                        tools = defaultdict(int)
                        successes = 0
                        for m in members:
                            tools[m['tool']] += 1
                            if m['success']:
                                successes += 1

                        cluster_id = hashlib.md5(str(key).encode()).hexdigest()[:16]
                        cluster_data = {
                            "keywords": list(key),
                            "size": len(members),
                            "success_rate": round(successes / len(members) * 100, 1),
                            "common_tools": dict(sorted(tools.items(), key=lambda x: x[1], reverse=True)[:5])
                        }

                        # Save to database
                        cur.execute("""
                            INSERT INTO query_clusters
                            (cluster_id, cluster_name, centroid_keywords, member_count,
                             avg_success_rate, common_tools)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (cluster_id) DO UPDATE SET
                                member_count = EXCLUDED.member_count,
                                avg_success_rate = EXCLUDED.avg_success_rate,
                                common_tools = EXCLUDED.common_tools,
                                updated_at = NOW()
                        """, (
                            cluster_id,
                            " + ".join(key[:3]),
                            json.dumps(list(key)),
                            len(members),
                            cluster_data['success_rate'],
                            json.dumps(cluster_data['common_tools'])
                        ))

                        valid_clusters.append(cluster_data)

                valid_clusters.sort(key=lambda x: x['size'], reverse=True)

                return {
                    "success": True,
                    "period_days": days,
                    "total_queries": len(query_data),
                    "clusters_found": len(valid_clusters),
                    "clusters": valid_clusters[:15]
                }

        except Exception as e:
            logger.error(f"Cluster queries failed: {e}")
            return {"success": False, "error": str(e)}

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract significant keywords from text."""
        # Simple keyword extraction
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                    'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                    'can', 'need', 'to', 'of', 'in', 'for', 'on', 'with', 'at',
                    'by', 'from', 'as', 'into', 'through', 'during', 'before',
                    'after', 'above', 'below', 'between', 'under', 'again', 'and',
                    'or', 'but', 'if', 'then', 'because', 'while', 'although',
                    'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'mein', 'dein',
                    'sein', 'ist', 'sind', 'war', 'waren', 'haben', 'hat', 'hatte',
                    'werden', 'wird', 'wurde', 'worden', 'und', 'oder', 'aber',
                    'wenn', 'dass', 'weil', 'obwohl', 'für', 'mit', 'von', 'zu',
                    'bei', 'nach', 'vor', 'über', 'unter', 'zwischen', 'durch',
                    'mir', 'dir', 'was', 'wie', 'wo', 'wer', 'wann', 'warum',
                    'bitte', 'please', 'thanks', 'danke', 'ja', 'nein', 'yes', 'no'}

        words = text.split()
        keywords = []
        for word in words:
            # Clean word
            clean = ''.join(c for c in word if c.isalnum())
            if clean and len(clean) > 2 and clean not in stopwords:
                keywords.append(clean)

        return keywords[:10]

    def detect_anomalies(
        self,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Detect anomalies in recent usage patterns.

        Identifies unusual patterns that might indicate issues.
        """
        try:
            anomalies = []

            with get_cursor() as cur:
                # Check for unusual failure rates
                cur.execute("""
                    SELECT tool_name,
                           COUNT(*) as total,
                           SUM(CASE WHEN success = false THEN 1 ELSE 0 END) as failures
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    GROUP BY tool_name
                    HAVING COUNT(*) >= 5
                """, (days,))

                for row in cur.fetchall():
                    fail_rate = row['failures'] / row['total']
                    if fail_rate > 0.5:  # More than 50% failure
                        anomaly = {
                            "type": "high_failure_rate",
                            "tool": row['tool_name'],
                            "rate": round(fail_rate * 100, 1),
                            "total": row['total'],
                            "severity": "high" if fail_rate > 0.7 else "medium"
                        }
                        anomalies.append(anomaly)

                        cur.execute("""
                            INSERT INTO usage_anomalies
                            (anomaly_type, description, severity, context_data)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            "high_failure_rate",
                            f"Tool {row['tool_name']} has {round(fail_rate*100)}% failure rate",
                            anomaly['severity'],
                            json.dumps(anomaly)
                        ))

                # Check for unusual activity spikes
                cur.execute("""
                    SELECT DATE(created_at) as day, COUNT(*) as count
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    GROUP BY DATE(created_at)
                    ORDER BY day
                """, (days,))

                daily_counts = [row['count'] for row in cur.fetchall()]
                if len(daily_counts) >= 3:
                    avg = sum(daily_counts) / len(daily_counts)
                    std = math.sqrt(sum((x - avg) ** 2 for x in daily_counts) / len(daily_counts))

                    for i, count in enumerate(daily_counts):
                        if std > 0 and abs(count - avg) > 2 * std:
                            direction = "spike" if count > avg else "drop"
                            anomalies.append({
                                "type": f"activity_{direction}",
                                "day_index": i,
                                "count": count,
                                "expected": round(avg),
                                "severity": "low"
                            })

                return {
                    "success": True,
                    "period_days": days,
                    "anomalies_found": len(anomalies),
                    "anomalies": anomalies
                }

        except Exception as e:
            logger.error(f"Detect anomalies failed: {e}")
            return {"success": False, "error": str(e)}

    def predict_next_tool(
        self,
        recent_tools: List[str],
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Predict the next likely tool based on patterns.

        Uses sequential and co-occurrence patterns.
        """
        try:
            if not recent_tools:
                return {"success": True, "prediction": None, "reason": "No recent tools"}

            last_tool = recent_tools[-1]

            with get_cursor() as cur:
                # Find tools that commonly follow the last tool
                cur.execute("""
                    SELECT chain_tools
                    FROM tool_chains
                    WHERE chain_tools->>0 = %s
                    ORDER BY occurrence_count DESC
                    LIMIT 5
                """, (last_tool,))

                predictions = []
                for row in cur.fetchall():
                    chain = row['chain_tools']
                    if len(chain) > 1:
                        next_tool = chain[1]
                        if next_tool not in recent_tools[-3:]:  # Avoid recent repetition
                            predictions.append(next_tool)

                if predictions:
                    # Record prediction for accuracy tracking
                    cur.execute("""
                        INSERT INTO pattern_predictions
                        (prediction_type, input_signature, predicted_value, confidence)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        "next_tool",
                        json.dumps({"recent": recent_tools[-3:]}),
                        predictions[0],
                        0.6
                    ))

                    return {
                        "success": True,
                        "predicted_tool": predictions[0],
                        "alternatives": predictions[1:4],
                        "based_on": f"patterns after {last_tool}",
                        "confidence": 0.6
                    }

                return {
                    "success": True,
                    "predicted_tool": None,
                    "reason": "No pattern found"
                }

        except Exception as e:
            logger.error(f"Predict next tool failed: {e}")
            return {"success": False, "error": str(e)}

    def _save_pattern(
        self,
        cur,
        pattern_type: str,
        pattern_name: str,
        pattern_data: Dict[str, Any],
        confidence: float
    ):
        """Save or update a recognized pattern."""
        pattern_id = hashlib.md5(
            f"{pattern_type}:{pattern_name}".encode()
        ).hexdigest()

        cur.execute("""
            INSERT INTO recognized_patterns
            (pattern_id, pattern_type, pattern_name, pattern_data, confidence)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (pattern_id) DO UPDATE SET
                pattern_data = EXCLUDED.pattern_data,
                confidence = EXCLUDED.confidence,
                occurrence_count = recognized_patterns.occurrence_count + 1,
                last_seen_at = NOW()
        """, (
            pattern_id,
            pattern_type,
            pattern_name,
            json.dumps(pattern_data),
            confidence
        ))

    def get_recognized_patterns(
        self,
        pattern_type: str = None,
        min_confidence: float = 0.3,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get recognized patterns."""
        try:
            with get_cursor() as cur:
                if pattern_type:
                    cur.execute("""
                        SELECT pattern_type, pattern_name, pattern_data,
                               confidence, occurrence_count, last_seen_at
                        FROM recognized_patterns
                        WHERE pattern_type = %s
                        AND confidence >= %s
                        AND is_active = true
                        ORDER BY confidence DESC
                        LIMIT %s
                    """, (pattern_type, min_confidence, limit))
                else:
                    cur.execute("""
                        SELECT pattern_type, pattern_name, pattern_data,
                               confidence, occurrence_count, last_seen_at
                        FROM recognized_patterns
                        WHERE confidence >= %s
                        AND is_active = true
                        ORDER BY confidence DESC
                        LIMIT %s
                    """, (min_confidence, limit))

                patterns = [{
                    "type": row['pattern_type'],
                    "name": row['pattern_name'],
                    "data": row['pattern_data'],
                    "confidence": round(row['confidence'], 3),
                    "occurrences": row['occurrence_count'],
                    "last_seen": row['last_seen_at'].isoformat()
                } for row in cur.fetchall()]

                return {
                    "success": True,
                    "patterns": patterns
                }

        except Exception as e:
            logger.error(f"Get recognized patterns failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[PatternRecognitionService] = None


def get_pattern_recognition_service() -> PatternRecognitionService:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = PatternRecognitionService()
    return _service
