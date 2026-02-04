"""
Relevance Engine - Memory Hygiene for Knowledge Items

Handles:
- Time-based relevance decay
- Reinforcement when knowledge is confirmed/used
- Archiving low-relevance items (never deletion)
- Cross-namespace access control
"""
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.relevance")


# ============ Configuration ============

# Relevance thresholds
ARCHIVE_THRESHOLD = 0.2       # Below this = candidate for archiving
LOW_RELEVANCE_THRESHOLD = 0.3 # Below this = flagged as low relevance
DECAY_FLOOR = 0.1             # Never decay below this

# Decay parameters
DECAY_HALF_LIFE_DAYS = 30     # Relevance halves every 30 days without reinforcement
DECAY_RATE = math.log(2) / DECAY_HALF_LIFE_DAYS

# Reinforcement parameters
REINFORCE_BOOST = 0.2         # How much to boost on reinforcement
REINFORCE_MAX = 1.0           # Max relevance score

# Time-based decay formula: new_score = old_score * e^(-decay_rate * days_since_last_seen)


# ============ Decay Operations ============

def calculate_decay(current_score: float, days_since_seen: float) -> float:
    """
    Calculate new relevance score based on time decay.

    Uses exponential decay with configurable half-life.
    """
    if days_since_seen <= 0:
        return current_score

    decayed = current_score * math.exp(-DECAY_RATE * days_since_seen)
    return max(DECAY_FLOOR, round(decayed, 3))


def decay_item(item_id: int, reason: str = None) -> Optional[Dict]:
    """
    Apply time-based decay to a single knowledge item.

    Returns updated item info or None on failure.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current state
            cur.execute("""
                SELECT id, relevance_score, last_seen_at
                FROM knowledge_item
                WHERE id = %s AND status = 'active'
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                return None

            current_score = row["relevance_score"]
            last_seen = row["last_seen_at"]

            # Calculate days since last seen
            now = datetime.utcnow()
            if last_seen:
                days_since = (now - last_seen.replace(tzinfo=None)).total_seconds() / 86400
            else:
                days_since = 30  # Default if never seen

            # Calculate new score
            new_score = calculate_decay(current_score, days_since)

            # Update
            cur.execute("""
                UPDATE knowledge_item
                SET relevance_score = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, relevance_score, status
            """, (new_score, item_id))

            result = dict(cur.fetchone())
            result["previous_score"] = current_score
            result["days_since_seen"] = round(days_since, 1)

            log_with_context(logger, "debug", "Item decayed",
                           item_id=item_id, old=current_score, new=new_score)

            return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to decay item",
                        item_id=item_id, error=str(e))
        return None


def decay_batch(
    namespace: str = None,
    item_type: str = None,
    min_days_since_seen: int = 7,
    limit: int = 100
) -> Dict:
    """
    Apply decay to multiple items that haven't been seen recently.

    Returns summary of decayed items.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            conditions = [
                "status = 'active'",
                "last_seen_at < NOW() - INTERVAL '%s days'" % min_days_since_seen
            ]
            params = []

            if namespace:
                conditions.append("namespace = %s")
                params.append(namespace)

            if item_type:
                conditions.append("item_type = %s")
                params.append(item_type)

            params.append(limit)

            cur.execute(f"""
                SELECT id, relevance_score, last_seen_at
                FROM knowledge_item
                WHERE {" AND ".join(conditions)}
                ORDER BY last_seen_at ASC
                LIMIT %s
            """, params)

            items = cur.fetchall()
            decayed_count = 0
            archive_candidates = 0

            for item in items:
                result = decay_item(item["id"])
                if result:
                    decayed_count += 1
                    if result["relevance_score"] < ARCHIVE_THRESHOLD:
                        archive_candidates += 1

            return {
                "processed": len(items),
                "decayed": decayed_count,
                "archive_candidates": archive_candidates
            }

    except Exception as e:
        log_with_context(logger, "error", "Failed to decay batch", error=str(e))
        return {"processed": 0, "decayed": 0, "archive_candidates": 0, "error": str(e)}


# ============ Reinforcement Operations ============

def reinforce_item(item_id: int, boost: float = None, reason: str = None) -> Optional[Dict]:
    """
    Reinforce a knowledge item (increase relevance when confirmed/used).

    Args:
        item_id: The item to reinforce
        boost: Optional custom boost amount (default: REINFORCE_BOOST)
        reason: Why this item was reinforced

    Returns updated item info.
    """
    if boost is None:
        boost = REINFORCE_BOOST

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current score
            cur.execute("""
                SELECT relevance_score FROM knowledge_item
                WHERE id = %s AND status = 'active'
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                return None

            current_score = row["relevance_score"]
            new_score = min(REINFORCE_MAX, current_score + boost)

            # Update with reinforcement
            cur.execute("""
                UPDATE knowledge_item
                SET relevance_score = %s,
                    last_seen_at = NOW(),
                    last_reinforced_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, relevance_score, status
            """, (new_score, item_id))

            result = dict(cur.fetchone())
            result["previous_score"] = current_score
            result["boost_applied"] = round(new_score - current_score, 3)

            log_with_context(logger, "info", "Item reinforced",
                           item_id=item_id, old=current_score, new=new_score, reason=reason)

            return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to reinforce item",
                        item_id=item_id, error=str(e))
        return None


def mark_seen(item_id: int) -> bool:
    """
    Mark an item as seen (updates last_seen_at without changing relevance).
    Use this when knowledge is accessed/displayed.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE knowledge_item
                SET last_seen_at = NOW()
                WHERE id = %s
            """, (item_id,))
            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to mark seen",
                        item_id=item_id, error=str(e))
        return False


# ============ Archive Operations ============

def archive_item(item_id: int, reason: str = None) -> Optional[Dict]:
    """
    Archive a knowledge item (status change, no deletion).

    Requires item to be below ARCHIVE_THRESHOLD or explicit reason.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current state
            cur.execute("""
                SELECT relevance_score, status FROM knowledge_item
                WHERE id = %s
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                return None

            if row["status"] == "archived":
                return {"id": item_id, "status": "archived", "already_archived": True}

            # Check threshold or require reason
            if row["relevance_score"] >= ARCHIVE_THRESHOLD and not reason:
                return {
                    "id": item_id,
                    "error": "relevance_above_threshold",
                    "relevance_score": row["relevance_score"],
                    "threshold": ARCHIVE_THRESHOLD,
                    "hint": "Provide explicit reason to archive high-relevance items"
                }

            # Archive
            cur.execute("""
                UPDATE knowledge_item
                SET status = 'archived', updated_at = NOW()
                WHERE id = %s
                RETURNING id, status, relevance_score
            """, (item_id,))

            result = dict(cur.fetchone())
            result["archived_reason"] = reason

            log_with_context(logger, "info", "Item archived",
                           item_id=item_id, reason=reason)

            return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to archive item",
                        item_id=item_id, error=str(e))
        return None


def unarchive_item(item_id: int, new_relevance: float = 0.5) -> Optional[Dict]:
    """
    Restore an archived item to active status.
    Sets a moderate relevance score.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                UPDATE knowledge_item
                SET status = 'active',
                    relevance_score = %s,
                    last_seen_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND status = 'archived'
                RETURNING id, status, relevance_score
            """, (new_relevance, item_id))

            row = cur.fetchone()
            if not row:
                return None

            log_with_context(logger, "info", "Item unarchived", item_id=item_id)
            return dict(row)

    except Exception as e:
        log_with_context(logger, "error", "Failed to unarchive item",
                        item_id=item_id, error=str(e))
        return None


def get_archive_candidates(
    namespace: str = None,
    threshold: float = None,
    limit: int = 20
) -> List[Dict]:
    """
    Get items that are candidates for archiving (below threshold).
    """
    if threshold is None:
        threshold = ARCHIVE_THRESHOLD

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            conditions = [
                "status = 'active'",
                "relevance_score < %s"
            ]
            params = [threshold]

            if namespace:
                conditions.append("namespace = %s")
                params.append(namespace)

            params.append(limit)

            cur.execute(f"""
                SELECT ki.*, kiv.content
                FROM knowledge_item ki
                LEFT JOIN knowledge_item_version kiv ON ki.current_version_id = kiv.id
                WHERE {" AND ".join(conditions)}
                ORDER BY relevance_score ASC
                LIMIT %s
            """, params)

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get archive candidates", error=str(e))
        return []


# ============ Relevance Stats ============

def get_relevance_distribution(namespace: str = None) -> Dict:
    """Get distribution of relevance scores."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            namespace_filter = "WHERE namespace = %s" if namespace else ""
            params = (namespace,) if namespace else ()

            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE relevance_score >= 0.8) as high,
                    COUNT(*) FILTER (WHERE relevance_score >= 0.5 AND relevance_score < 0.8) as medium,
                    COUNT(*) FILTER (WHERE relevance_score >= 0.3 AND relevance_score < 0.5) as low,
                    COUNT(*) FILTER (WHERE relevance_score < 0.3) as very_low,
                    COUNT(*) FILTER (WHERE relevance_score < %s) as archive_candidates
                FROM knowledge_item
                {namespace_filter}
                {"AND" if namespace else "WHERE"} status = 'active'
            """, (ARCHIVE_THRESHOLD,) + params)

            row = cur.fetchone()
            result = dict(row) if row else {}
            result["thresholds"] = {
                "archive": ARCHIVE_THRESHOLD,
                "low_relevance": LOW_RELEVANCE_THRESHOLD
            }
            return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to get relevance distribution", error=str(e))
        return {}
