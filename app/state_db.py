"""
Ingest state tracking - Postgres primary backend with SQLite for meta-reflection tables

Phase 11: Uses postgres_state.py for core state (ingest, conversations, telegram, working_state)
SQLite is kept for meta-reflection tables (decision_log, reflection_log, blind_spot_log, etc.)
"""
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import os

# Import Postgres backend for core state functions
from . import postgres_state as pg

DB_PATH = Path(os.environ.get("BRAIN_ROOT", "/brain")) / "index" / "ingest_state.db"

def _get_conn():
    """Get SQLite connection for meta-reflection tables"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    return conn

def init_db():
    """Initialize SQLite schema for meta-reflection tables only"""
    conn = _get_conn()

    # Decision log for meta-reflection and pattern analysis
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            context_summary TEXT NOT NULL,
            options TEXT,
            chosen_option TEXT,
            confidence INTEGER,
            energy_cost_expected INTEGER,
            tags TEXT,
            outcome_recorded_at TEXT,
            outcome_rating INTEGER,
            outcome_notes TEXT,
            user_id INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_tags ON decision_log(tags)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_created ON decision_log(created_at DESC)")

    # Add flags columns to decision_log if they don't exist
    try:
        conn.execute("ALTER TABLE decision_log ADD COLUMN red_flags TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE decision_log ADD COLUMN green_flags TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Reflection log for inner compass, reality checks, etc.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reflection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            reflection_type TEXT NOT NULL,
            context TEXT NOT NULL,
            insights TEXT,
            head_says TEXT,
            heart_says TEXT,
            fear_says TEXT,
            wisdom_says TEXT,
            alignment_score INTEGER,
            decision_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY (decision_id) REFERENCES decision_log(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reflection_type ON reflection_log(reflection_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reflection_user ON reflection_log(user_id)")

    # Blind spot tracking - when user's prediction differs significantly from outcome
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blind_spot_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            pattern_type TEXT NOT NULL,
            description TEXT NOT NULL,
            occurrences INTEGER DEFAULT 1,
            last_triggered TEXT,
            user_id INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blindspot_user ON blind_spot_log(user_id)")

    conn.commit()
    conn.close()

def is_already_ingested(source_path: str, ingest_type: str) -> bool:
    """Check if source was successfully ingested - delegates to Postgres"""
    return pg.is_already_ingested(source_path, ingest_type)


def record_ingest(
    source_path: str,
    namespace: str,
    ingest_type: str,
    ingest_ts: str,
    chunks_upserted: int,
    status: str = "success",
    error_msg: Optional[str] = None
):
    """Record ingest attempt (upsert) - delegates to Postgres"""
    pg.record_ingest(source_path, namespace, ingest_type, ingest_ts, chunks_upserted, status, error_msg)


def get_ingest_history(
    namespace: Optional[str] = None,
    ingest_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query ingest history with filters - delegates to Postgres"""
    return pg.get_ingest_history(namespace, ingest_type, status, limit)


def get_ingest_stats() -> Dict[str, Any]:
    """Get aggregate stats for health checks - delegates to Postgres"""
    return pg.get_ingest_stats()

# ============ Conversation Memory Functions ============
# NOTE: These delegate to postgres_state.py for primary storage

def create_session(session_id: str, namespace: str) -> str:
    """Create a new conversation session - delegates to Postgres"""
    return pg.create_session(session_id, namespace)


def add_message(
    session_id: str,
    role: str,
    content: str,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    sources: Optional[List[str]] = None,
    source: Optional[str] = None
):
    """Add a message to a conversation - delegates to Postgres

    Args:
        source: Origin of message (telegram, claude_code, copilot, api, etc.)
    """
    pg.add_message(session_id, role, content, tokens_in, tokens_out, sources, source)


def get_conversation_history(
    session_id: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get recent messages from a conversation - delegates to Postgres"""
    return pg.get_conversation_history(session_id, limit)


def get_session_info(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session metadata - queries Postgres"""
    with pg.get_dict_cursor() as cur:
        cur.execute("SELECT * FROM conversation WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_sessions(namespace: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """List recent conversation sessions - queries Postgres"""
    with pg.get_dict_cursor() as cur:
        if namespace:
            cur.execute("""
                SELECT * FROM conversation
                WHERE namespace = %s
                ORDER BY updated_at DESC
                LIMIT %s
            """, (namespace, limit))
        else:
            cur.execute("""
                SELECT * FROM conversation
                ORDER BY updated_at DESC
                LIMIT %s
            """, (limit,))
        return [dict(row) for row in cur.fetchall()]


def update_session_title(session_id: str, title: str):
    """Update session title - updates Postgres"""
    with pg.get_cursor() as cur:
        cur.execute("""
            UPDATE conversation SET title = %s WHERE session_id = %s
        """, (title, session_id))


# ============ Telegram User State Functions ============
# NOTE: These delegate to postgres_state.py for primary storage

def get_telegram_user_state(user_id: int) -> Dict[str, Any]:
    """Get telegram user's session state - delegates to Postgres"""
    return pg.get_telegram_user_state(user_id)


def set_telegram_user_state(
    user_id: int,
    session_id: str = None,
    namespace: str = None,
    role: str = None
):
    """Update telegram user's state (upsert) - delegates to Postgres"""
    pg.set_telegram_user_state(user_id, session_id, namespace, role)


def get_all_telegram_users() -> List[Dict[str, Any]]:
    """Get all registered telegram users - delegates to Postgres"""
    return pg.get_all_telegram_users()


# ============ Decision Log Functions ============
# NOTE: Decision log stays in SQLite for now (meta-reflection tables)

def log_decision(
    context_summary: str,
    tags: List[str] = None,
    options: List[str] = None,
    chosen_option: str = None,
    confidence: int = None,
    energy_cost_expected: int = None,
    user_id: int = None
) -> int:
    """
    Log a decision for later reflection.

    Args:
        context_summary: Brief description of the decision context
        tags: Categories like ["team", "tech", "personal", "finance"]
        options: List of options considered (optional)
        chosen_option: Which option was chosen (optional)
        confidence: 1-10 how confident you feel (optional)
        energy_cost_expected: 1-10 expected energy cost (optional)
        user_id: Telegram user ID (optional)

    Returns:
        The decision ID
    """
    import json
    now = datetime.now().isoformat(timespec="seconds")

    conn = _get_conn()
    cursor = conn.execute("""
        INSERT INTO decision_log
        (created_at, context_summary, options, chosen_option, confidence,
         energy_cost_expected, tags, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now,
        context_summary,
        json.dumps(options) if options else None,
        chosen_option,
        confidence,
        energy_cost_expected,
        json.dumps(tags) if tags else None,
        user_id
    ))
    decision_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return decision_id


def record_outcome(
    decision_id: int,
    outcome_rating: int,
    outcome_notes: str = None
):
    """
    Record the outcome of a past decision.

    Args:
        decision_id: ID of the decision to update
        outcome_rating: 1-10 how it turned out
        outcome_notes: Optional notes on what happened
    """
    now = datetime.now().isoformat(timespec="seconds")

    conn = _get_conn()
    conn.execute("""
        UPDATE decision_log
        SET outcome_recorded_at = ?, outcome_rating = ?, outcome_notes = ?
        WHERE id = ?
    """, (now, outcome_rating, outcome_notes, decision_id))
    conn.commit()
    conn.close()


def get_recent_decisions(
    limit: int = 20,
    user_id: int = None,
    tags: List[str] = None,
    pending_outcome: bool = False
) -> List[Dict[str, Any]]:
    """Get recent decisions, optionally filtered."""
    import json
    conn = _get_conn()

    query = "SELECT * FROM decision_log WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    if pending_outcome:
        query += " AND outcome_recorded_at IS NULL"

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    decisions = []
    for row in rows:
        d = dict(row)
        if d.get("options"):
            d["options"] = json.loads(d["options"])
        if d.get("tags"):
            d["tags"] = json.loads(d["tags"])
        # Filter by tags if specified
        if tags and d.get("tags"):
            if not any(t in d["tags"] for t in tags):
                continue
        decisions.append(d)

    return decisions


def get_decision_patterns(user_id: int = None) -> Dict[str, Any]:
    """
    Analyze decision patterns for self-trust tracking.

    Returns stats on confidence vs outcome correlation,
    accuracy by tag, etc.
    """
    import json
    conn = _get_conn()

    query = """
        SELECT * FROM decision_log
        WHERE outcome_rating IS NOT NULL
    """
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"message": "Not enough data yet", "total_decisions": 0}

    # Analyze patterns
    total = len(rows)
    confidence_vs_outcome = []
    by_tag = {}

    for row in rows:
        d = dict(row)
        conf = d.get("confidence")
        outcome = d.get("outcome_rating")

        if conf and outcome:
            confidence_vs_outcome.append({
                "confidence": conf,
                "outcome": outcome,
                "delta": outcome - conf  # positive = better than expected
            })

        # Aggregate by tag
        tags = json.loads(d["tags"]) if d.get("tags") else ["untagged"]
        for tag in tags:
            if tag not in by_tag:
                by_tag[tag] = {"count": 0, "avg_confidence": 0, "avg_outcome": 0, "outcomes": []}
            by_tag[tag]["count"] += 1
            if conf:
                by_tag[tag]["avg_confidence"] += conf
            if outcome:
                by_tag[tag]["outcomes"].append(outcome)

    # Calculate averages
    for tag, stats in by_tag.items():
        if stats["count"] > 0:
            stats["avg_confidence"] = round(stats["avg_confidence"] / stats["count"], 1)
        if stats["outcomes"]:
            stats["avg_outcome"] = round(sum(stats["outcomes"]) / len(stats["outcomes"]), 1)
            # Confidence accuracy: how often outcome >= confidence
            stats["confidence_accuracy"] = None  # TODO: calculate when we have more data
        del stats["outcomes"]

    # Overall confidence accuracy
    if confidence_vs_outcome:
        avg_delta = sum(c["delta"] for c in confidence_vs_outcome) / len(confidence_vs_outcome)
        accurate_count = sum(1 for c in confidence_vs_outcome if c["outcome"] >= c["confidence"])
        accuracy_pct = round(100 * accurate_count / len(confidence_vs_outcome))
    else:
        avg_delta = 0
        accuracy_pct = None

    return {
        "total_decisions": total,
        "with_outcomes": len(confidence_vs_outcome),
        "avg_confidence_delta": round(avg_delta, 1) if confidence_vs_outcome else None,
        "confidence_accuracy_pct": accuracy_pct,
        "by_tag": by_tag,
        "insight": _generate_insight(by_tag, accuracy_pct, avg_delta) if total >= 5 else "Need more data (at least 5 decisions with outcomes)"
    }


def _generate_insight(by_tag: Dict, accuracy_pct: int, avg_delta: float) -> str:
    """Generate a human-readable insight from decision patterns."""
    insights = []

    if accuracy_pct is not None:
        if accuracy_pct >= 70:
            insights.append(f"Your confidence is well-calibrated ({accuracy_pct}% accurate).")
        elif accuracy_pct >= 50:
            insights.append(f"Your confidence is moderately accurate ({accuracy_pct}%).")
        else:
            insights.append(f"You tend to be overconfident ({accuracy_pct}% accuracy). Consider more caution.")

    if avg_delta > 1:
        insights.append("Outcomes generally exceed your expectations.")
    elif avg_delta < -1:
        insights.append("Outcomes often fall below expectations.")

    # Find best/worst tag
    if by_tag:
        sorted_tags = sorted(
            [(k, v) for k, v in by_tag.items() if v.get("avg_outcome") and v["count"] >= 2],
            key=lambda x: x[1]["avg_outcome"],
            reverse=True
        )
        if sorted_tags:
            best = sorted_tags[0]
            insights.append(f"Best outcomes in '{best[0]}' decisions (avg {best[1]['avg_outcome']}/10).")
            if len(sorted_tags) > 1:
                worst = sorted_tags[-1]
                if worst[1]["avg_outcome"] < best[1]["avg_outcome"] - 2:
                    insights.append(f"Consider more caution with '{worst[0]}' decisions (avg {worst[1]['avg_outcome']}/10).")

    return " ".join(insights) if insights else "Collecting more data for insights."


# ============ Reflection Log Functions ============

def log_reflection(
    reflection_type: str,
    context: str,
    insights: str = None,
    head_says: str = None,
    heart_says: str = None,
    fear_says: str = None,
    wisdom_says: str = None,
    alignment_score: int = None,
    decision_id: int = None,
    user_id: int = None
) -> int:
    """
    Log a reflection (compass reading, reality check, etc.)

    Args:
        reflection_type: "compass", "reality", "assumptions", "consequences"
        context: The situation being reflected on
        insights: Key insights gained
        head_says/heart_says/fear_says/wisdom_says: For compass reflections
        alignment_score: 1-10 how aligned head/heart are
        decision_id: Link to a specific decision
        user_id: Telegram user ID

    Returns:
        The reflection ID
    """
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_conn()
    cursor = conn.execute("""
        INSERT INTO reflection_log
        (created_at, reflection_type, context, insights, head_says, heart_says,
         fear_says, wisdom_says, alignment_score, decision_id, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now, reflection_type, context, insights, head_says, heart_says,
        fear_says, wisdom_says, alignment_score, decision_id, user_id
    ))
    reflection_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return reflection_id


def get_recent_reflections(
    user_id: int = None,
    reflection_type: str = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Get recent reflections."""
    conn = _get_conn()
    query = "SELECT * FROM reflection_log WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if reflection_type:
        query += " AND reflection_type = ?"
        params.append(reflection_type)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ============ Flag Functions (Red/Green Flags) ============

def add_flags_to_decision(
    decision_id: int,
    red_flags: List[str] = None,
    green_flags: List[str] = None
):
    """Add red/green flags to an existing decision."""
    import json
    conn = _get_conn()

    updates = []
    params = []

    if red_flags:
        updates.append("red_flags = ?")
        params.append(json.dumps(red_flags))
    if green_flags:
        updates.append("green_flags = ?")
        params.append(json.dumps(green_flags))

    if updates:
        params.append(decision_id)
        conn.execute(
            f"UPDATE decision_log SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()
    conn.close()


def get_flag_patterns(user_id: int = None) -> Dict[str, Any]:
    """
    Analyze red/green flag patterns from past decisions.
    Returns common flags and their correlation with outcomes.
    """
    import json
    conn = _get_conn()

    query = """
        SELECT red_flags, green_flags, outcome_rating, tags
        FROM decision_log
        WHERE outcome_rating IS NOT NULL
    """
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    red_flag_stats = {}  # flag -> [outcomes]
    green_flag_stats = {}

    for row in rows:
        outcome = row["outcome_rating"]

        if row["red_flags"]:
            for flag in json.loads(row["red_flags"]):
                if flag not in red_flag_stats:
                    red_flag_stats[flag] = []
                red_flag_stats[flag].append(outcome)

        if row["green_flags"]:
            for flag in json.loads(row["green_flags"]):
                if flag not in green_flag_stats:
                    green_flag_stats[flag] = []
                green_flag_stats[flag].append(outcome)

    # Calculate averages
    red_summary = {}
    for flag, outcomes in red_flag_stats.items():
        red_summary[flag] = {
            "count": len(outcomes),
            "avg_outcome": round(sum(outcomes) / len(outcomes), 1)
        }

    green_summary = {}
    for flag, outcomes in green_flag_stats.items():
        green_summary[flag] = {
            "count": len(outcomes),
            "avg_outcome": round(sum(outcomes) / len(outcomes), 1)
        }

    return {
        "red_flags": red_summary,
        "green_flags": green_summary,
        "total_analyzed": len(rows)
    }


# ============ Self-Trust Tracker ============

def get_self_trust_metrics(user_id: int = None) -> Dict[str, Any]:
    """
    Calculate self-trust metrics: how reliable is the user's intuition?
    Based on confidence vs. outcome correlation over time.
    """
    import json
    conn = _get_conn()

    query = """
        SELECT confidence, outcome_rating, energy_cost_expected, tags, created_at
        FROM decision_log
        WHERE outcome_rating IS NOT NULL AND confidence IS NOT NULL
    """
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    query += " ORDER BY created_at DESC"

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 3:
        return {
            "status": "need_more_data",
            "message": f"Need at least 3 decisions with outcomes. Currently have {len(rows)}.",
            "total_tracked": len(rows)
        }

    # Calculate metrics
    total = len(rows)
    accurate = 0  # confidence matched outcome within 2 points
    overconfident = 0  # confidence > outcome by 3+
    underconfident = 0  # confidence < outcome by 3+

    recent_accuracy = []  # Last 5 decisions
    historical_accuracy = []  # Older decisions

    for i, row in enumerate(rows):
        conf = row["confidence"]
        outcome = row["outcome_rating"]
        delta = outcome - conf

        if abs(delta) <= 2:
            accurate += 1
            is_accurate = True
        elif delta < -2:
            overconfident += 1
            is_accurate = False
        else:
            underconfident += 1
            is_accurate = False

        if i < 5:
            recent_accuracy.append(is_accurate)
        else:
            historical_accuracy.append(is_accurate)

    # Calculate trend
    recent_pct = (sum(recent_accuracy) / len(recent_accuracy) * 100) if recent_accuracy else 0
    historical_pct = (sum(historical_accuracy) / len(historical_accuracy) * 100) if historical_accuracy else recent_pct

    if recent_pct > historical_pct + 10:
        trend = "improving"
        trend_emoji = "📈"
    elif recent_pct < historical_pct - 10:
        trend = "declining"
        trend_emoji = "📉"
    else:
        trend = "stable"
        trend_emoji = "➡️"

    # Generate trust level
    accuracy_pct = round(accurate / total * 100)
    if accuracy_pct >= 70:
        trust_level = "high"
        trust_emoji = "🟢"
    elif accuracy_pct >= 50:
        trust_level = "moderate"
        trust_emoji = "🟡"
    else:
        trust_level = "developing"
        trust_emoji = "🟠"

    return {
        "total_tracked": total,
        "accuracy_pct": accuracy_pct,
        "accurate_count": accurate,
        "overconfident_count": overconfident,
        "underconfident_count": underconfident,
        "trust_level": trust_level,
        "trust_emoji": trust_emoji,
        "trend": trend,
        "trend_emoji": trend_emoji,
        "recent_accuracy_pct": round(recent_pct),
        "insight": _generate_trust_insight(accuracy_pct, overconfident, underconfident, trend, total)
    }


def _generate_trust_insight(accuracy_pct: int, overconf: int, underconf: int, trend: str, total: int) -> str:
    """Generate human-readable insight about self-trust."""
    insights = []

    if accuracy_pct >= 70:
        insights.append(f"Your intuition is well-calibrated ({accuracy_pct}% accurate).")
    elif accuracy_pct >= 50:
        insights.append(f"Your intuition is moderately reliable ({accuracy_pct}%).")
    else:
        insights.append(f"Your self-assessment needs calibration ({accuracy_pct}% accurate).")

    if overconf > underconf * 2:
        insights.append("You tend toward overconfidence - consider adding a buffer.")
    elif underconf > overconf * 2:
        insights.append("You underestimate yourself - trust your gut more.")

    if trend == "improving":
        insights.append("Your calibration is improving over time!")
    elif trend == "declining":
        insights.append("Recent predictions less accurate - pause and reflect.")

    return " ".join(insights)


# ============ Blind Spot Functions ============

def record_blind_spot(
    pattern_type: str,
    description: str,
    user_id: int = None
):
    """Record a detected blind spot pattern."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_conn()

    # Check if this pattern already exists
    cursor = conn.execute("""
        SELECT id, occurrences FROM blind_spot_log
        WHERE pattern_type = ? AND user_id = ?
    """, (pattern_type, user_id))
    existing = cursor.fetchone()

    if existing:
        conn.execute("""
            UPDATE blind_spot_log
            SET occurrences = occurrences + 1, last_triggered = ?, description = ?
            WHERE id = ?
        """, (now, description, existing["id"]))
    else:
        conn.execute("""
            INSERT INTO blind_spot_log (created_at, pattern_type, description, last_triggered, user_id)
            VALUES (?, ?, ?, ?, ?)
        """, (now, pattern_type, description, now, user_id))

    conn.commit()
    conn.close()


def get_blind_spots(user_id: int = None) -> List[Dict[str, Any]]:
    """Get recorded blind spot patterns for a user."""
    conn = _get_conn()
    query = "SELECT * FROM blind_spot_log WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    query += " ORDER BY occurrences DESC, last_triggered DESC"

    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def detect_blind_spots(user_id: int = None) -> List[Dict[str, str]]:
    """
    Analyze decision history to detect potential blind spots.
    Returns list of detected patterns.
    """
    import json
    conn = _get_conn()

    query = """
        SELECT confidence, outcome_rating, tags, context_summary
        FROM decision_log
        WHERE outcome_rating IS NOT NULL
    """
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 5:
        return []

    blind_spots = []

    # Pattern 1: Consistent overconfidence in specific tags
    tag_deltas = {}
    for row in rows:
        if row["confidence"] and row["outcome_rating"]:
            tags = json.loads(row["tags"]) if row["tags"] else ["general"]
            delta = row["outcome_rating"] - row["confidence"]
            for tag in tags:
                if tag not in tag_deltas:
                    tag_deltas[tag] = []
                tag_deltas[tag].append(delta)

    for tag, deltas in tag_deltas.items():
        if len(deltas) >= 3:
            avg_delta = sum(deltas) / len(deltas)
            if avg_delta < -2:
                blind_spots.append({
                    "type": "overconfidence",
                    "description": f"Consistently overconfident in '{tag}' decisions (avg {abs(round(avg_delta, 1))} points too high)"
                })
            elif avg_delta > 2:
                blind_spots.append({
                    "type": "underconfidence",
                    "description": f"Consistently underestimate yourself in '{tag}' decisions (outcomes avg {round(avg_delta, 1)} better)"
                })

    # Pattern 2: High energy cost correlating with poor outcomes
    energy_outcomes = [(r["energy_cost_expected"], r["outcome_rating"])
                       for r in rows if r.get("energy_cost_expected")]
    if len(energy_outcomes) >= 3:
        high_energy = [o for e, o in energy_outcomes if e and e >= 7]
        low_energy = [o for e, o in energy_outcomes if e and e <= 4]
        if high_energy and low_energy:
            avg_high = sum(high_energy) / len(high_energy)
            avg_low = sum(low_energy) / len(low_energy)
            if avg_high < avg_low - 2:
                blind_spots.append({
                    "type": "energy_drain",
                    "description": f"High-energy decisions tend to have worse outcomes (avg {round(avg_high, 1)} vs {round(avg_low, 1)})"
                })

    return blind_spots


# ============ Energy Cost Estimator ============

def get_energy_stats(user_id: int = None) -> Dict[str, Any]:
    """
    Analyze energy cost patterns from decision history.
    Helps calibrate future energy estimates.
    """
    import json
    conn = _get_conn()

    query = """
        SELECT energy_cost_expected, outcome_rating, tags, context_summary
        FROM decision_log
        WHERE energy_cost_expected IS NOT NULL
    """
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"status": "no_data", "message": "No decisions with energy ratings yet."}

    total = len(rows)
    energies = [r["energy_cost_expected"] for r in rows]
    avg_energy = round(sum(energies) / len(energies), 1)

    # Energy by tag
    by_tag = {}
    for row in rows:
        tags = json.loads(row["tags"]) if row["tags"] else ["general"]
        for tag in tags:
            if tag not in by_tag:
                by_tag[tag] = {"energies": [], "outcomes": []}
            by_tag[tag]["energies"].append(row["energy_cost_expected"])
            if row["outcome_rating"]:
                by_tag[tag]["outcomes"].append(row["outcome_rating"])

    tag_summary = {}
    for tag, data in by_tag.items():
        if len(data["energies"]) >= 2:
            tag_summary[tag] = {
                "count": len(data["energies"]),
                "avg_energy": round(sum(data["energies"]) / len(data["energies"]), 1),
                "avg_outcome": round(sum(data["outcomes"]) / len(data["outcomes"]), 1) if data["outcomes"] else None
            }

    # High energy decisions
    high_energy = [r for r in rows if r["energy_cost_expected"] >= 7]
    high_energy_pct = round(len(high_energy) / total * 100)

    return {
        "total_tracked": total,
        "avg_energy": avg_energy,
        "high_energy_pct": high_energy_pct,
        "by_tag": tag_summary,
        "insight": f"Average energy cost: {avg_energy}/10. {high_energy_pct}% of decisions rated as high-energy (7+)."
    }


# ============ Feedback Storage ============

def _init_feedback_table():
    """Create feedback table if not exists"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_category ON user_feedback(category)")
    conn.commit()
    conn.close()


def store_feedback(user_id: int, category: str, description: str, timestamp: str):
    """Store user feedback about Jarvis responses"""
    _init_feedback_table()
    conn = _get_conn()
    conn.execute("""
        INSERT INTO user_feedback (user_id, category, description, timestamp)
        VALUES (?, ?, ?, ?)
    """, (user_id, category, description, timestamp))
    conn.commit()
    conn.close()
    # Feedback stored successfully


def get_feedback_summary(user_id: int = None, days: int = 30) -> Dict[str, Any]:
    """Get feedback summary"""
    _init_feedback_table()
    conn = _get_conn()

    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    if user_id:
        rows = conn.execute("""
            SELECT category, COUNT(*) as count
            FROM user_feedback
            WHERE user_id = ? AND timestamp > ?
            GROUP BY category
        """, (user_id, cutoff)).fetchall()
    else:
        rows = conn.execute("""
            SELECT category, COUNT(*) as count
            FROM user_feedback
            WHERE timestamp > ?
            GROUP BY category
        """, (cutoff,)).fetchall()

    conn.close()

    summary = {row[0]: row[1] for row in rows}
    total = sum(summary.values())

    return {
        "total": total,
        "by_category": summary,
        "days": days
    }


# ============ Message Feedback (Per-Response Ratings) ============

def _init_message_feedback_table():
    """Create message feedback table if not exists"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            session_id TEXT,
            rating TEXT NOT NULL,
            query_preview TEXT,
            response_preview TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_feedback_user ON message_feedback(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_feedback_rating ON message_feedback(rating)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_feedback_time ON message_feedback(timestamp)")
    conn.commit()
    conn.close()


def store_message_feedback(
    user_id: int,
    message_id: int,
    rating: str,
    session_id: str = None,
    query_preview: str = None,
    response_preview: str = None
):
    """Store feedback for a specific message response.

    Args:
        user_id: Telegram user ID
        message_id: Telegram message ID that was rated
        rating: 'good', 'ok', or 'bad'
        session_id: Optional session ID for context
        query_preview: First 100 chars of user's query
        response_preview: First 100 chars of Jarvis response
    """
    from datetime import datetime
    _init_message_feedback_table()
    conn = _get_conn()
    conn.execute("""
        INSERT INTO message_feedback
        (user_id, message_id, session_id, rating, query_preview, response_preview, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, message_id, session_id, rating, query_preview, response_preview, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_message_feedback_stats(user_id: int = None, days: int = 30) -> Dict[str, Any]:
    """Get message feedback statistics.

    Returns:
        Dict with total count, breakdown by rating, and recent feedback
    """
    from datetime import datetime, timedelta
    _init_message_feedback_table()
    conn = _get_conn()

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # Get counts by rating
    if user_id:
        rows = conn.execute("""
            SELECT rating, COUNT(*) as count
            FROM message_feedback
            WHERE user_id = ? AND timestamp > ?
            GROUP BY rating
        """, (user_id, cutoff)).fetchall()
    else:
        rows = conn.execute("""
            SELECT rating, COUNT(*) as count
            FROM message_feedback
            WHERE timestamp > ?
            GROUP BY rating
        """, (cutoff,)).fetchall()

    by_rating = {row[0]: row[1] for row in rows}
    total = sum(by_rating.values())

    # Calculate satisfaction score (good=1, ok=0.5, bad=0)
    good = by_rating.get('good', 0)
    ok = by_rating.get('ok', 0)
    bad = by_rating.get('bad', 0)

    if total > 0:
        satisfaction = (good * 1.0 + ok * 0.5 + bad * 0.0) / total
    else:
        satisfaction = None

    conn.close()

    return {
        "total": total,
        "by_rating": by_rating,
        "satisfaction_score": round(satisfaction, 2) if satisfaction else None,
        "days": days
    }


# ============ Working State (Session Memory) ============
# NOTE: These delegate to postgres_state.py for primary storage

def get_working_state(state_id: str = "default") -> Optional[Dict[str, Any]]:
    """Get current working state for session continuity - delegates to Postgres"""
    return pg.get_working_state(state_id)


def set_working_state(
    state_id: str = "default",
    active_threads: List[str] = None,
    open_questions: List[str] = None,
    partial_results: Dict[str, Any] = None,
    resume_hint: str = None,
    momentum: str = None
):
    """Save working state for session continuity - delegates to Postgres"""
    pg.set_working_state(state_id, active_threads, open_questions, partial_results, resume_hint, momentum)


def clear_working_state(state_id: str = "default"):
    """Clear working state (e.g., on explicit session end) - delegates to Postgres"""
    pg.clear_working_state(state_id)


# ============ Follow-up Tracking ============

def _init_followups_table():
    """Create followups table if not exists"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            -- Source information
            source_type TEXT NOT NULL,  -- 'email', 'chat', 'session', 'manual'
            source_id TEXT,             -- email_id, chat_id, etc.
            source_from TEXT,           -- sender/person

            -- Content
            subject TEXT NOT NULL,
            description TEXT,
            keyword_detected TEXT,      -- what triggered detection

            -- Tracking
            due_date TEXT,              -- YYYY-MM-DD or YYYY-MM-DD HH:MM
            status TEXT DEFAULT 'pending',  -- pending, in_progress, done, dismissed
            priority TEXT DEFAULT 'normal', -- low, normal, high, urgent

            -- Resolution
            completed_at TEXT,
            completion_notes TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_followup_status ON followups(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_followup_due ON followups(due_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_followup_source ON followups(source_type, source_from)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_followup_priority ON followups(priority)")
    conn.commit()
    conn.close()


def create_followup(
    subject: str,
    source_type: str = "manual",
    source_id: str = None,
    source_from: str = None,
    description: str = None,
    keyword_detected: str = None,
    due_date: str = None,
    priority: str = "normal"
) -> str:
    """
    Create a new follow-up item.

    Args:
        subject: Brief description of what needs follow-up
        source_type: Where this came from ('email', 'chat', 'session', 'manual')
        source_id: ID of source item (email_id, etc.)
        source_from: Person/sender name
        description: Additional details
        keyword_detected: Keyword that triggered detection
        due_date: When this is due (YYYY-MM-DD)
        priority: 'low', 'normal', 'high', 'urgent'

    Returns:
        The follow-up ID
    """
    import uuid
    _init_followups_table()

    followup_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat(timespec="seconds")

    conn = _get_conn()
    conn.execute("""
        INSERT INTO followups
        (id, created_at, updated_at, source_type, source_id, source_from,
         subject, description, keyword_detected, due_date, priority)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        followup_id, now, now, source_type, source_id, source_from,
        subject, description, keyword_detected, due_date, priority
    ))
    conn.commit()
    conn.close()

    return followup_id


def get_followup(followup_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific follow-up by ID"""
    _init_followups_table()
    conn = _get_conn()
    cursor = conn.execute("SELECT * FROM followups WHERE id = ?", (followup_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_followups(
    status: str = None,
    priority: str = None,
    source_type: str = None,
    include_done: bool = False,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    List follow-ups with optional filters.

    Args:
        status: Filter by status ('pending', 'in_progress', 'done', 'dismissed')
        priority: Filter by priority
        source_type: Filter by source type
        include_done: Include completed/dismissed items
        limit: Maximum items to return
    """
    _init_followups_table()
    conn = _get_conn()

    query = "SELECT * FROM followups WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    elif not include_done:
        query += " AND status NOT IN ('done', 'dismissed')"

    if priority:
        query += " AND priority = ?"
        params.append(priority)

    if source_type:
        query += " AND source_type = ?"
        params.append(source_type)

    # Order by: priority (urgent first), then due date, then created
    query += """
        ORDER BY
            CASE priority
                WHEN 'urgent' THEN 1
                WHEN 'high' THEN 2
                WHEN 'normal' THEN 3
                WHEN 'low' THEN 4
            END,
            CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
            due_date,
            created_at DESC
        LIMIT ?
    """
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def update_followup(
    followup_id: str,
    status: str = None,
    priority: str = None,
    due_date: str = None,
    description: str = None,
    completion_notes: str = None
) -> bool:
    """
    Update a follow-up item.

    Returns True if updated, False if not found.
    """
    _init_followups_table()
    now = datetime.now().isoformat(timespec="seconds")

    conn = _get_conn()

    # Check if exists
    cursor = conn.execute("SELECT id FROM followups WHERE id = ?", (followup_id,))
    if not cursor.fetchone():
        conn.close()
        return False

    updates = ["updated_at = ?"]
    params = [now]

    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status == "done":
            updates.append("completed_at = ?")
            params.append(now)

    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)

    if due_date is not None:
        updates.append("due_date = ?")
        params.append(due_date)

    if description is not None:
        updates.append("description = ?")
        params.append(description)

    if completion_notes is not None:
        updates.append("completion_notes = ?")
        params.append(completion_notes)

    params.append(followup_id)
    conn.execute(
        f"UPDATE followups SET {', '.join(updates)} WHERE id = ?",
        params
    )
    conn.commit()
    conn.close()
    return True


def complete_followup(followup_id: str, notes: str = None) -> bool:
    """Mark a follow-up as done"""
    return update_followup(followup_id, status="done", completion_notes=notes)


def dismiss_followup(followup_id: str, notes: str = None) -> bool:
    """Dismiss a follow-up (no longer relevant)"""
    return update_followup(followup_id, status="dismissed", completion_notes=notes)


def get_overdue_followups() -> List[Dict[str, Any]]:
    """Get follow-ups that are past their due date"""
    _init_followups_table()
    today = datetime.now().strftime("%Y-%m-%d")

    conn = _get_conn()
    cursor = conn.execute("""
        SELECT * FROM followups
        WHERE status NOT IN ('done', 'dismissed')
        AND due_date IS NOT NULL
        AND due_date < ?
        ORDER BY due_date, priority
    """, (today,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_followup_stats() -> Dict[str, Any]:
    """Get statistics about follow-ups"""
    _init_followups_table()
    conn = _get_conn()

    # Count by status
    cursor = conn.execute("""
        SELECT status, COUNT(*) as count
        FROM followups
        GROUP BY status
    """)
    by_status = {row["status"]: row["count"] for row in cursor.fetchall()}

    # Count by priority (pending only)
    cursor = conn.execute("""
        SELECT priority, COUNT(*) as count
        FROM followups
        WHERE status NOT IN ('done', 'dismissed')
        GROUP BY priority
    """)
    by_priority = {row["priority"]: row["count"] for row in cursor.fetchall()}

    # Count by source type (pending only)
    cursor = conn.execute("""
        SELECT source_type, COUNT(*) as count
        FROM followups
        WHERE status NOT IN ('done', 'dismissed')
        GROUP BY source_type
    """)
    by_source = {row["source_type"]: row["count"] for row in cursor.fetchall()}

    # Overdue count
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.execute("""
        SELECT COUNT(*) as count
        FROM followups
        WHERE status NOT IN ('done', 'dismissed')
        AND due_date IS NOT NULL
        AND due_date < ?
    """, (today,))
    overdue_count = cursor.fetchone()["count"]

    conn.close()

    return {
        "by_status": by_status,
        "by_priority": by_priority,
        "by_source": by_source,
        "overdue_count": overdue_count,
        "total_pending": sum(c for s, c in by_status.items() if s not in ("done", "dismissed")),
        "total_completed": by_status.get("done", 0)
    }


def find_existing_followup(source_type: str, source_id: str) -> Optional[Dict[str, Any]]:
    """Check if a follow-up already exists for a source (dedupe)"""
    _init_followups_table()
    conn = _get_conn()
    cursor = conn.execute("""
        SELECT * FROM followups
        WHERE source_type = ? AND source_id = ?
        AND status NOT IN ('done', 'dismissed')
    """, (source_type, source_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ============ Email Pattern Learning ============

def _init_email_patterns_table():
    """Create email_patterns table if not exists"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id TEXT UNIQUE,
            thread_id TEXT,
            direction TEXT NOT NULL,   -- 'inbound' or 'outbound'
            contact_email TEXT NOT NULL,
            contact_name TEXT,
            subject TEXT,
            timestamp TEXT NOT NULL,   -- ISO format
            response_to_id TEXT,       -- ID of email this responds to
            response_time_hours REAL   -- Hours to respond (if this is a response)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_contact ON email_interactions(contact_email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_thread ON email_interactions(thread_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_direction ON email_interactions(direction)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_timestamp ON email_interactions(timestamp)")

    # Aggregated patterns per contact
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_contact_patterns (
            contact_email TEXT PRIMARY KEY,
            contact_name TEXT,
            total_emails_received INTEGER DEFAULT 0,
            total_emails_sent INTEGER DEFAULT 0,
            total_responses_received INTEGER DEFAULT 0,
            avg_response_time_hours REAL,
            min_response_time_hours REAL,
            max_response_time_hours REAL,
            typical_response_day TEXT,      -- 'weekday', 'weekend', 'any'
            typical_response_hour INTEGER,  -- Most common hour (0-23)
            last_interaction TEXT,          -- ISO timestamp
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def record_email_interaction(
    email_id: str,
    direction: str,
    contact_email: str,
    timestamp: str,
    thread_id: str = None,
    contact_name: str = None,
    subject: str = None,
    response_to_id: str = None
) -> Dict[str, Any]:
    """
    Record an email interaction for pattern learning.

    Args:
        email_id: Unique email ID
        direction: 'inbound' (received) or 'outbound' (sent)
        contact_email: The other party's email
        timestamp: ISO format timestamp
        thread_id: Email thread ID
        contact_name: Display name of contact
        subject: Email subject
        response_to_id: ID of email this responds to

    Returns:
        Dict with recorded data and calculated response time
    """
    _init_email_patterns_table()
    conn = _get_conn()

    # Calculate response time if this is a response
    response_time_hours = None
    if response_to_id:
        cursor = conn.execute(
            "SELECT timestamp FROM email_interactions WHERE email_id = ?",
            (response_to_id,)
        )
        row = cursor.fetchone()
        if row:
            original_time = datetime.fromisoformat(row["timestamp"])
            response_time = datetime.fromisoformat(timestamp)
            delta = response_time - original_time
            response_time_hours = delta.total_seconds() / 3600

    # Insert interaction (ignore duplicates)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO email_interactions
            (email_id, thread_id, direction, contact_email, contact_name,
             subject, timestamp, response_to_id, response_time_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            email_id, thread_id, direction, contact_email.lower(), contact_name,
            subject, timestamp, response_to_id, response_time_hours
        ))
        conn.commit()
    except Exception:
        pass  # Duplicate, ignore

    conn.close()

    # Update aggregated patterns
    _update_contact_patterns(contact_email.lower())

    return {
        "email_id": email_id,
        "direction": direction,
        "contact_email": contact_email,
        "response_time_hours": response_time_hours
    }


def _update_contact_patterns(contact_email: str):
    """Update aggregated patterns for a contact"""
    conn = _get_conn()

    # Get all interactions for this contact
    cursor = conn.execute("""
        SELECT
            direction,
            response_time_hours,
            timestamp
        FROM email_interactions
        WHERE contact_email = ?
        ORDER BY timestamp
    """, (contact_email,))
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return

    # Calculate stats
    received = sum(1 for r in rows if r["direction"] == "inbound")
    sent = sum(1 for r in rows if r["direction"] == "outbound")
    response_times = [r["response_time_hours"] for r in rows
                      if r["response_time_hours"] is not None and r["direction"] == "inbound"]

    # Calculate response time stats
    avg_response = sum(response_times) / len(response_times) if response_times else None
    min_response = min(response_times) if response_times else None
    max_response = max(response_times) if response_times else None

    # Analyze typical response times
    response_hours = []
    for row in rows:
        if row["direction"] == "inbound" and row["response_time_hours"]:
            ts = datetime.fromisoformat(row["timestamp"])
            response_hours.append(ts.hour)

    typical_hour = None
    if response_hours:
        # Find most common hour
        from collections import Counter
        hour_counts = Counter(response_hours)
        typical_hour = hour_counts.most_common(1)[0][0]

    # Get contact name from most recent interaction
    cursor = conn.execute("""
        SELECT contact_name FROM email_interactions
        WHERE contact_email = ? AND contact_name IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, (contact_email,))
    name_row = cursor.fetchone()
    contact_name = name_row["contact_name"] if name_row else None

    last_ts = max(r["timestamp"] for r in rows)
    now = datetime.now().isoformat(timespec="seconds")

    # Upsert patterns
    conn.execute("""
        INSERT OR REPLACE INTO email_contact_patterns
        (contact_email, contact_name, total_emails_received, total_emails_sent,
         total_responses_received, avg_response_time_hours, min_response_time_hours,
         max_response_time_hours, typical_response_hour, last_interaction, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        contact_email, contact_name, received, sent,
        len(response_times), avg_response, min_response,
        max_response, typical_hour, last_ts, now
    ))
    conn.commit()
    conn.close()


def get_contact_pattern(contact_email: str) -> Optional[Dict[str, Any]]:
    """Get learned patterns for a specific contact"""
    _init_email_patterns_table()
    conn = _get_conn()
    cursor = conn.execute(
        "SELECT * FROM email_contact_patterns WHERE contact_email = ?",
        (contact_email.lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def predict_response_time(contact_email: str) -> Dict[str, Any]:
    """
    Predict when a contact is likely to respond.

    Returns:
        Dict with prediction info including expected hours, confidence, etc.
    """
    pattern = get_contact_pattern(contact_email.lower())

    if not pattern:
        return {
            "contact": contact_email,
            "prediction": "unknown",
            "message": "No interaction history with this contact",
            "suggested_followup_hours": 48  # Default: 2 days
        }

    avg_hours = pattern.get("avg_response_time_hours")
    responses = pattern.get("total_responses_received", 0)

    if not avg_hours or responses < 2:
        return {
            "contact": contact_email,
            "prediction": "insufficient_data",
            "message": f"Only {responses} response(s) recorded",
            "suggested_followup_hours": 48
        }

    # Categorize response speed
    if avg_hours < 2:
        speed = "very_fast"
        description = "Usually responds within 2 hours"
    elif avg_hours < 8:
        speed = "fast"
        description = "Usually responds same day"
    elif avg_hours < 24:
        speed = "normal"
        description = "Usually responds within 24 hours"
    elif avg_hours < 72:
        speed = "slow"
        description = "Usually takes 1-3 days to respond"
    else:
        speed = "very_slow"
        description = f"Average response time: {int(avg_hours / 24)} days"

    # Suggest follow-up time (1.5x average, but at least 24 hours)
    suggested = max(24, avg_hours * 1.5)

    return {
        "contact": contact_email,
        "contact_name": pattern.get("contact_name"),
        "prediction": speed,
        "description": description,
        "avg_response_hours": round(avg_hours, 1),
        "min_response_hours": round(pattern.get("min_response_time_hours") or 0, 1),
        "max_response_hours": round(pattern.get("max_response_time_hours") or 0, 1),
        "typical_hour": pattern.get("typical_response_hour"),
        "data_points": responses,
        "suggested_followup_hours": round(suggested),
        "last_interaction": pattern.get("last_interaction")
    }


def list_contact_patterns(
    min_interactions: int = 3,
    order_by: str = "last_interaction",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    List all contact patterns.

    Args:
        min_interactions: Minimum emails to include
        order_by: 'last_interaction', 'avg_response', 'total_emails'
        limit: Maximum results
    """
    _init_email_patterns_table()
    conn = _get_conn()

    order_clause = {
        "last_interaction": "last_interaction DESC",
        "avg_response": "avg_response_time_hours ASC",
        "total_emails": "(total_emails_received + total_emails_sent) DESC"
    }.get(order_by, "last_interaction DESC")

    cursor = conn.execute(f"""
        SELECT * FROM email_contact_patterns
        WHERE (total_emails_received + total_emails_sent) >= ?
        ORDER BY {order_clause}
        LIMIT ?
    """, (min_interactions, limit))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_email_pattern_stats() -> Dict[str, Any]:
    """Get overall email pattern statistics"""
    _init_email_patterns_table()
    conn = _get_conn()

    # Total interactions
    cursor = conn.execute("SELECT COUNT(*) as count FROM email_interactions")
    total_interactions = cursor.fetchone()["count"]

    # Total contacts with patterns
    cursor = conn.execute("SELECT COUNT(*) as count FROM email_contact_patterns")
    total_contacts = cursor.fetchone()["count"]

    # Contacts by response speed
    cursor = conn.execute("""
        SELECT
            CASE
                WHEN avg_response_time_hours < 2 THEN 'very_fast'
                WHEN avg_response_time_hours < 8 THEN 'fast'
                WHEN avg_response_time_hours < 24 THEN 'normal'
                WHEN avg_response_time_hours < 72 THEN 'slow'
                ELSE 'very_slow'
            END as speed_category,
            COUNT(*) as count
        FROM email_contact_patterns
        WHERE avg_response_time_hours IS NOT NULL
        GROUP BY speed_category
    """)
    by_speed = {row["speed_category"]: row["count"] for row in cursor.fetchall()}

    # Overall average response time
    cursor = conn.execute("""
        SELECT AVG(avg_response_time_hours) as avg
        FROM email_contact_patterns
        WHERE avg_response_time_hours IS NOT NULL
    """)
    overall_avg = cursor.fetchone()["avg"]

    conn.close()

    return {
        "total_interactions": total_interactions,
        "total_contacts_tracked": total_contacts,
        "contacts_by_speed": by_speed,
        "overall_avg_response_hours": round(overall_avg, 1) if overall_avg else None
    }


# ============ Conflict Detection ============

def _init_conflicts_table():
    """Create conflicts tracking tables if not exist"""
    conn = _get_conn()

    # Migration: Rename 'values' column to 'conflict_values' (values is reserved in SQLite)
    try:
        cursor = conn.execute("PRAGMA table_info(conflicts)")
        columns = [row[1] for row in cursor.fetchall()]
        if "values" in columns and "conflict_values" not in columns:
            # Old schema detected - recreate table with correct column name
            conn.execute("ALTER TABLE conflicts RENAME TO conflicts_old")
            conn.execute("""
                CREATE TABLE conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    attribute TEXT NOT NULL,
                    fact_ids TEXT NOT NULL,
                    conflict_values TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    resolution TEXT,
                    resolved_by TEXT,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO conflicts (id, entity_type, entity_id, attribute, fact_ids,
                    conflict_values, status, resolution, resolved_by, resolved_at, created_at, updated_at)
                SELECT id, entity_type, entity_id, attribute, fact_ids,
                    "values", status, resolution, resolved_by, resolved_at, created_at, updated_at
                FROM conflicts_old
            """)
            conn.execute("DROP TABLE conflicts_old")
            conn.commit()
    except Exception:
        pass  # Table doesn't exist yet, will be created below

    # Facts table - stores claimed facts from various sources
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,      -- 'person', 'project', 'company', 'event'
            entity_id TEXT NOT NULL,        -- identifier (email, name, project_id)
            attribute TEXT NOT NULL,        -- what's being claimed (title, birthday, status)
            value TEXT NOT NULL,            -- the claimed value
            source_type TEXT NOT NULL,      -- 'email', 'chat', 'profile', 'calendar', 'manual'
            source_id TEXT,                 -- reference to source document
            source_date TEXT,               -- when the source was created
            confidence REAL DEFAULT 1.0,    -- 0.0 to 1.0
            created_at TEXT NOT NULL,
            is_current BOOLEAN DEFAULT 1,   -- is this the current truth?
            superseded_by INTEGER,          -- reference to newer fact
            UNIQUE(entity_type, entity_id, attribute, value, source_type, source_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_type, entity_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_attribute ON facts(attribute)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_current ON facts(is_current)")

    # Conflicts table - detected conflicts between facts
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            attribute TEXT NOT NULL,
            fact_ids TEXT NOT NULL,         -- JSON array of conflicting fact IDs
            conflict_values TEXT NOT NULL,  -- JSON array of conflicting values
            status TEXT DEFAULT 'open',     -- 'open', 'resolved', 'ignored'
            resolution TEXT,                -- which value is correct
            resolved_by TEXT,               -- 'user', 'auto', 'newer_wins'
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_entity ON conflicts(entity_type, entity_id)")

    conn.commit()
    conn.close()


def record_fact(
    entity_type: str,
    entity_id: str,
    attribute: str,
    value: str,
    source_type: str,
    source_id: str = None,
    source_date: str = None,
    confidence: float = 1.0
) -> Dict[str, Any]:
    """
    Record a fact about an entity. Automatically detects conflicts.

    Args:
        entity_type: Type of entity ('person', 'project', 'company', 'event')
        entity_id: Unique identifier for the entity
        attribute: The attribute being claimed (e.g., 'title', 'birthday', 'status')
        value: The claimed value
        source_type: Where this fact came from
        source_id: Reference to source document
        source_date: When the source was created
        confidence: Confidence level 0.0 to 1.0

    Returns:
        Dict with fact_id and any detected conflict
    """
    import json
    _init_conflicts_table()

    now = datetime.now().isoformat(timespec="seconds")
    source_date = source_date or now

    conn = _get_conn()

    # Insert the fact (ignore if duplicate)
    try:
        cursor = conn.execute("""
            INSERT INTO facts
            (entity_type, entity_id, attribute, value, source_type, source_id,
             source_date, confidence, created_at, is_current)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            entity_type, entity_id.lower(), attribute, value,
            source_type, source_id, source_date, confidence, now
        ))
        fact_id = cursor.lastrowid
        conn.commit()
    except Exception:
        # Duplicate fact, find existing
        cursor = conn.execute("""
            SELECT id FROM facts
            WHERE entity_type = ? AND entity_id = ? AND attribute = ?
            AND value = ? AND source_type = ? AND source_id = ?
        """, (entity_type, entity_id.lower(), attribute, value, source_type, source_id))
        row = cursor.fetchone()
        fact_id = row["id"] if row else None
        conn.close()
        return {"fact_id": fact_id, "status": "duplicate", "conflict": None}

    # Check for conflicts - other facts about same entity+attribute with different values
    cursor = conn.execute("""
        SELECT id, value, source_type, source_date, confidence
        FROM facts
        WHERE entity_type = ? AND entity_id = ? AND attribute = ?
        AND value != ? AND is_current = 1
    """, (entity_type, entity_id.lower(), attribute, value))
    conflicting_facts = cursor.fetchall()

    conflict_info = None
    if conflicting_facts:
        # Conflict detected!
        all_fact_ids = [fact_id] + [f["id"] for f in conflicting_facts]
        all_values = [value] + [f["value"] for f in conflicting_facts]

        # Check if conflict already exists
        cursor = conn.execute("""
            SELECT id FROM conflicts
            WHERE entity_type = ? AND entity_id = ? AND attribute = ?
            AND status = 'open'
        """, (entity_type, entity_id.lower(), attribute))
        existing = cursor.fetchone()

        if existing:
            # Update existing conflict
            conn.execute("""
                UPDATE conflicts
                SET fact_ids = ?, conflict_values = ?, updated_at = ?
                WHERE id = ?
            """, (json.dumps(all_fact_ids), json.dumps(all_values), now, existing["id"]))
            conflict_id = existing["id"]
        else:
            # Create new conflict
            cursor = conn.execute("""
                INSERT INTO conflicts
                (entity_type, entity_id, attribute, fact_ids, conflict_values, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entity_type, entity_id.lower(), attribute,
                json.dumps(all_fact_ids), json.dumps(all_values), now, now
            ))
            conflict_id = cursor.lastrowid

        conn.commit()
        conflict_info = {
            "conflict_id": conflict_id,
            "conflicting_values": all_values,
            "fact_count": len(all_fact_ids)
        }

    conn.close()

    return {
        "fact_id": fact_id,
        "status": "recorded",
        "conflict": conflict_info
    }


def get_facts_for_entity(
    entity_type: str,
    entity_id: str,
    attribute: str = None,
    current_only: bool = True
) -> List[Dict[str, Any]]:
    """Get all facts for an entity, optionally filtered by attribute."""
    _init_conflicts_table()
    conn = _get_conn()

    query = "SELECT * FROM facts WHERE entity_type = ? AND entity_id = ?"
    params = [entity_type, entity_id.lower()]

    if attribute:
        query += " AND attribute = ?"
        params.append(attribute)

    if current_only:
        query += " AND is_current = 1"

    query += " ORDER BY source_date DESC"

    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_current_truth(entity_type: str, entity_id: str) -> Dict[str, Any]:
    """
    Get the current truth for an entity - one value per attribute.
    Uses: resolved conflicts > highest confidence > newest source.
    """
    import json
    _init_conflicts_table()
    conn = _get_conn()

    # Get all current facts
    cursor = conn.execute("""
        SELECT attribute, value, source_type, source_date, confidence
        FROM facts
        WHERE entity_type = ? AND entity_id = ? AND is_current = 1
        ORDER BY confidence DESC, source_date DESC
    """, (entity_type, entity_id.lower()))

    facts = cursor.fetchall()

    # Get resolved conflicts to override
    cursor = conn.execute("""
        SELECT attribute, resolution
        FROM conflicts
        WHERE entity_type = ? AND entity_id = ? AND status = 'resolved'
    """, (entity_type, entity_id.lower()))
    resolved = {r["attribute"]: r["resolution"] for r in cursor.fetchall()}

    conn.close()

    # Build current truth - one value per attribute
    truth = {}
    seen_attributes = set()

    for fact in facts:
        attr = fact["attribute"]
        if attr in seen_attributes:
            continue

        # Use resolved value if available
        if attr in resolved:
            truth[attr] = {
                "value": resolved[attr],
                "source": "resolved_conflict",
                "confidence": 1.0
            }
        else:
            truth[attr] = {
                "value": fact["value"],
                "source": fact["source_type"],
                "confidence": fact["confidence"],
                "source_date": fact["source_date"]
            }
        seen_attributes.add(attr)

    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "attributes": truth
    }


def list_conflicts(
    status: str = "open",
    entity_type: str = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """List conflicts, optionally filtered by status and entity type."""
    import json
    _init_conflicts_table()
    conn = _get_conn()

    query = "SELECT * FROM conflicts WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = []
    for row in cursor.fetchall():
        r = dict(row)
        r["fact_ids"] = json.loads(r["fact_ids"])
        r["values"] = json.loads(r["conflict_values"])
        del r["conflict_values"]  # Clean up, use "values" in response
        rows.append(r)

    conn.close()
    return rows


def resolve_conflict(
    conflict_id: int,
    resolution: str,
    resolved_by: str = "user"
) -> bool:
    """
    Resolve a conflict by choosing the correct value.

    Args:
        conflict_id: The conflict to resolve
        resolution: The correct value
        resolved_by: Who/what resolved it ('user', 'auto', 'newer_wins')

    Returns:
        True if resolved, False if not found
    """
    import json
    _init_conflicts_table()
    now = datetime.now().isoformat(timespec="seconds")

    conn = _get_conn()

    # Get conflict
    cursor = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,))
    conflict = cursor.fetchone()
    if not conflict:
        conn.close()
        return False

    # Mark conflict as resolved
    conn.execute("""
        UPDATE conflicts
        SET status = 'resolved', resolution = ?, resolved_by = ?, resolved_at = ?, updated_at = ?
        WHERE id = ?
    """, (resolution, resolved_by, now, now, conflict_id))

    # Mark non-matching facts as not current
    fact_ids = json.loads(conflict["fact_ids"])
    for fid in fact_ids:
        cursor = conn.execute("SELECT value FROM facts WHERE id = ?", (fid,))
        fact = cursor.fetchone()
        if fact and fact["value"] != resolution:
            conn.execute("UPDATE facts SET is_current = 0 WHERE id = ?", (fid,))

    conn.commit()
    conn.close()
    return True


def ignore_conflict(conflict_id: int) -> bool:
    """Mark a conflict as ignored (not a real conflict)."""
    _init_conflicts_table()
    now = datetime.now().isoformat(timespec="seconds")

    conn = _get_conn()
    cursor = conn.execute("SELECT id FROM conflicts WHERE id = ?", (conflict_id,))
    if not cursor.fetchone():
        conn.close()
        return False

    conn.execute("""
        UPDATE conflicts SET status = 'ignored', updated_at = ? WHERE id = ?
    """, (now, conflict_id))
    conn.commit()
    conn.close()
    return True


def get_conflict_stats() -> Dict[str, Any]:
    """Get conflict statistics."""
    _init_conflicts_table()
    conn = _get_conn()

    # Count by status
    cursor = conn.execute("""
        SELECT status, COUNT(*) as count FROM conflicts GROUP BY status
    """)
    by_status = {row["status"]: row["count"] for row in cursor.fetchall()}

    # Count by entity type (open only)
    cursor = conn.execute("""
        SELECT entity_type, COUNT(*) as count FROM conflicts
        WHERE status = 'open' GROUP BY entity_type
    """)
    by_entity = {row["entity_type"]: row["count"] for row in cursor.fetchall()}

    # Total facts
    cursor = conn.execute("SELECT COUNT(*) as count FROM facts")
    total_facts = cursor.fetchone()["count"]

    # Current facts
    cursor = conn.execute("SELECT COUNT(*) as count FROM facts WHERE is_current = 1")
    current_facts = cursor.fetchone()["count"]

    conn.close()

    return {
        "conflicts_by_status": by_status,
        "open_conflicts_by_entity": by_entity,
        "total_open": by_status.get("open", 0),
        "total_resolved": by_status.get("resolved", 0),
        "total_facts": total_facts,
        "current_facts": current_facts
    }


# Initialize DB on module import
init_db()
