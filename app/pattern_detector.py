"""
Jarvis Pattern Detector
Identifies recurring patterns in user interactions for proactive assistance.
"""
import json
import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.patterns")

# Use same DB as session_manager for topic_mentions
STATE_DB_PATH = os.environ.get("JARVIS_STATE_DB", "/brain/system/state/jarvis_state.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(STATE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(STATE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


PATTERN_TYPES = {
    "recurring_topic": "Topic erscheint regelmaessig",
    "person_related": "Haeufige Fragen zu einer Person",
    "unresolved_loop": "Gleiches Thema ohne Abschluss",
}

# Known person names to detect
KNOWN_PERSONS = ["philippe", "patrik", "martina", "micha", "michael"]


@dataclass
class Pattern:
    """Represents a detected pattern in user interactions"""
    pattern_type: str           # recurring_topic, person_related, etc.
    description: str            # Human-readable description
    confidence: float           # 0.0 - 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""
    occurrences: int = 0
    actionable: bool = True     # Should Jarvis mention it?

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_recurring_topics(
    user_id: int = None,
    min_count: int = 2,
    days: int = 30
) -> List[Pattern]:
    """
    Find topics that have been mentioned multiple times.
    Uses topic_mentions table from session_manager.
    """
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    query = """
        SELECT topic,
               SUM(mention_count) as total_mentions,
               MIN(first_mentioned) as first_seen,
               MAX(last_mentioned) as last_seen,
               COUNT(DISTINCT session_id) as session_count
        FROM topic_mentions
        WHERE last_mentioned > ?
    """
    params = [cutoff]

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    query += " GROUP BY topic HAVING total_mentions >= ? ORDER BY total_mentions DESC LIMIT 20"
    params.append(min_count)

    try:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        log_with_context(logger, "warning", "Topic table not available", error=str(e))
        conn.close()
        return []

    conn.close()

    patterns = []
    for row in rows:
        topic = row["topic"]
        count = row["total_mentions"]
        sessions = row["session_count"]

        # Calculate confidence based on frequency and recency
        days_since_last = (datetime.now() - datetime.fromisoformat(row["last_seen"])).days
        recency_factor = max(0.5, 1.0 - (days_since_last / days))
        confidence = min(1.0, (count / 10) * recency_factor)

        pattern = Pattern(
            pattern_type="recurring_topic",
            description=f'"{topic}" wurde {count}x in {sessions} Sessions erwaehnt',
            confidence=round(confidence, 2),
            evidence={
                "topic": topic,
                "mention_count": count,
                "session_count": sessions
            },
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            occurrences=count,
            actionable=count >= 3  # Only actionable if mentioned 3+ times
        )
        patterns.append(pattern)

    log_with_context(logger, "debug", "Recurring topics detected", count=len(patterns))
    return patterns


def detect_person_patterns(user_id: int = None, days: int = 30) -> List[Pattern]:
    """
    Find frequently mentioned persons in topics.
    """
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    patterns = []

    for person in KNOWN_PERSONS:
        query = """
            SELECT topic,
                   SUM(mention_count) as total_mentions,
                   MIN(first_mentioned) as first_seen,
                   MAX(last_mentioned) as last_seen
            FROM topic_mentions
            WHERE last_mentioned > ?
              AND LOWER(topic) LIKE ?
        """
        params = [cutoff, f"%{person}%"]

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += " GROUP BY topic"

        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            continue

        # Aggregate all mentions of this person
        total_mentions = sum(row["total_mentions"] for row in rows)
        if total_mentions >= 2:
            first_seen = min((row["first_seen"] for row in rows), default="")
            last_seen = max((row["last_seen"] for row in rows), default="")

            related_topics = [row["topic"] for row in rows]

            pattern = Pattern(
                pattern_type="person_related",
                description=f"{person.capitalize()} wurde {total_mentions}x erwaehnt",
                confidence=min(1.0, total_mentions / 10),
                evidence={
                    "person": person,
                    "mention_count": total_mentions,
                    "related_topics": related_topics[:5]
                },
                first_seen=first_seen,
                last_seen=last_seen,
                occurrences=total_mentions,
                actionable=total_mentions >= 3
            )
            patterns.append(pattern)

    conn.close()
    log_with_context(logger, "debug", "Person patterns detected", count=len(patterns))
    return patterns


def detect_unresolved_topics(user_id: int = None, days: int = 14) -> List[Pattern]:
    """
    Find topics that keep recurring without resolution.
    A topic is "unresolved" if it appears in multiple sessions
    but there's no completed pending action related to it.
    """
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # Get topics mentioned in 3+ sessions
    query = """
        SELECT tm.topic,
               COUNT(DISTINCT tm.session_id) as session_count,
               MAX(tm.last_mentioned) as last_seen
        FROM topic_mentions tm
        WHERE tm.last_mentioned > ?
    """
    params = [cutoff]

    if user_id:
        query += " AND tm.user_id = ?"
        params.append(user_id)

    query += " GROUP BY tm.topic HAVING session_count >= 3 ORDER BY session_count DESC LIMIT 10"

    try:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    patterns = []
    for row in rows:
        topic = row["topic"]
        sessions = row["session_count"]

        pattern = Pattern(
            pattern_type="unresolved_loop",
            description=f'"{topic}" taucht in {sessions} Sessions auf - noch offen?',
            confidence=min(1.0, sessions / 5),
            evidence={
                "topic": topic,
                "session_count": sessions
            },
            first_seen="",
            last_seen=row["last_seen"],
            occurrences=sessions,
            actionable=True
        )
        patterns.append(pattern)

    conn.close()
    return patterns


def get_relevant_patterns(
    user_id: int = None,
    current_query: str = None,
    days: int = 30
) -> List[Pattern]:
    """
    Main entry point: Get patterns relevant to the current context.

    Args:
        user_id: Filter patterns by user
        current_query: Current query to check for topic matches
        days: How many days to look back

    Returns:
        List of relevant patterns sorted by relevance
    """
    all_patterns = []

    # Get recurring topics
    recurring = detect_recurring_topics(user_id=user_id, days=days)
    all_patterns.extend(recurring)

    # Get person patterns
    persons = detect_person_patterns(user_id=user_id, days=days)
    all_patterns.extend(persons)

    # Get unresolved topics (shorter window)
    unresolved = detect_unresolved_topics(user_id=user_id, days=min(days, 14))
    all_patterns.extend(unresolved)

    # If current_query is provided, boost relevance of matching patterns
    if current_query:
        query_lower = current_query.lower()
        for pattern in all_patterns:
            # Check if query mentions the pattern's topic/person
            topic = pattern.evidence.get("topic", "")
            person = pattern.evidence.get("person", "")

            if topic and topic.lower() in query_lower:
                pattern.confidence = min(1.0, pattern.confidence + 0.3)
                pattern.actionable = True
            if person and person.lower() in query_lower:
                pattern.confidence = min(1.0, pattern.confidence + 0.3)
                pattern.actionable = True

    # Filter to actionable patterns only
    actionable = [p for p in all_patterns if p.actionable]

    # Sort by confidence descending
    actionable.sort(key=lambda p: p.confidence, reverse=True)

    # Limit to top 5 most relevant
    return actionable[:5]


def build_pattern_context(patterns: List[Pattern]) -> str:
    """
    Format patterns as a context string for the agent system prompt.

    Args:
        patterns: List of detected patterns

    Returns:
        Formatted string to inject into system prompt
    """
    if not patterns:
        return ""

    lines = ["=== ERKANNTE PATTERNS ==="]

    for p in patterns:
        type_label = PATTERN_TYPES.get(p.pattern_type, p.pattern_type)
        lines.append(f"- [{p.pattern_type}] {p.description}")

        # Add context for unresolved topics
        if p.pattern_type == "unresolved_loop":
            lines.append(f"  (Erwaege nachzufragen ob das Thema noch relevant ist)")

    lines.append("")
    lines.append("Nutze diese Patterns um proaktiv zu sein - erwaehne relevante Zusammenhaenge.")

    return "\n".join(lines)


def get_pattern_stats(user_id: int = None, days: int = 30) -> Dict[str, Any]:
    """
    Get statistics about detected patterns for API/debugging.
    """
    recurring = detect_recurring_topics(user_id=user_id, min_count=1, days=days)
    persons = detect_person_patterns(user_id=user_id, days=days)
    unresolved = detect_unresolved_topics(user_id=user_id, days=min(days, 14))

    return {
        "recurring_topics": {
            "count": len(recurring),
            "patterns": [p.to_dict() for p in recurring[:10]]
        },
        "person_patterns": {
            "count": len(persons),
            "patterns": [p.to_dict() for p in persons]
        },
        "unresolved_topics": {
            "count": len(unresolved),
            "patterns": [p.to_dict() for p in unresolved[:5]]
        },
        "days_analyzed": days,
        "user_id": user_id
    }
