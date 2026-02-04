"""
Jarvis Memory Store
Persistent storage for facts Jarvis learns about the user.
"""
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import hashlib

from .observability import get_logger, log_with_context
from .utils.timezone import ZURICH_TZ

logger = get_logger("jarvis.memory")

DB_PATH = os.environ.get("JARVIS_MEMORY_DB", "/brain/system/state/jarvis_memory.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the memory database"""
    conn = _get_conn()

    # Facts table - things Jarvis learns about the user
    # trust_score: 0.0-1.0, increases with usage, facts with high score are migration candidates
    # access_count: how often this fact was recalled/used
    # last_accessed: when fact was last used
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            fact TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT,
            confidence REAL DEFAULT 1.0,
            active INTEGER DEFAULT 1,
            trust_score REAL DEFAULT 0.0,
            access_count INTEGER DEFAULT 0,
            last_accessed TEXT,
            migrated INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(active)")

    # Migration to add new columns if table already exists (v2.2)
    try:
        conn.execute("ALTER TABLE facts ADD COLUMN trust_score REAL DEFAULT 0.0")
        log_with_context(logger, "info", "Added trust_score column to facts table")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE facts ADD COLUMN access_count INTEGER DEFAULT 0")
        log_with_context(logger, "info", "Added access_count column to facts table")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE facts ADD COLUMN last_accessed TEXT")
        log_with_context(logger, "info", "Added last_accessed column to facts table")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE facts ADD COLUMN migrated INTEGER DEFAULT 0")
        log_with_context(logger, "info", "Added migrated column to facts table")
    except sqlite3.OperationalError:
        pass

    # Create index on trust_score AFTER migration ensures column exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_trust ON facts(trust_score)")

    # Entities table - people, projects, companies
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)")

    # Entity relationships
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            related_entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES entities(id),
            FOREIGN KEY (related_entity_id) REFERENCES entities(id)
        )
    """)

    conn.commit()
    conn.close()
    log_with_context(logger, "info", "Memory store initialized", db_path=DB_PATH)


def _make_fact_id(fact: str, category: str) -> str:
    """Generate deterministic ID for a fact"""
    key = f"{category}::{fact[:100]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def add_fact(
    fact: str,
    category: str,
    source: str = None,
    confidence: float = 1.0,
    initial_trust_score: float = 0.0
) -> str:
    """
    Add or update a fact about the user.
    Returns the fact ID.

    Args:
        fact: The fact text to store
        category: Category (preference, relationship, project, personal, work)
        source: Where this fact came from (e.g., "user_explicit", "inferred")
        confidence: How confident we are in this fact (0.0-1.0)
        initial_trust_score: Starting trust score (0.0-1.0)
            - 0.0: Default, needs to prove itself through usage
            - 0.3: User mentioned it explicitly
            - 0.5: User confirmed it
            - 0.7: Repeatedly validated

    Trust Score Lifecycle:
        remember_fact() → SQLite (trust_score starts at initial_trust_score)
             ↓ (each access: +0.1, max 1.0)
        Bewährtes Wissen (trust_score >= 0.5, access_count >= 5)
             ↓ (Claude Code Review)
        Migration → Config/YAML/Code (permanent)
    """
    now = datetime.now(ZURICH_TZ).isoformat(timespec="seconds")
    fact_id = _make_fact_id(fact, category)

    # Clamp initial_trust_score to valid range
    initial_trust_score = max(0.0, min(1.0, initial_trust_score))

    conn = _get_conn()
    conn.execute("""
        INSERT INTO facts (id, fact, category, created_at, updated_at, source, confidence, active, trust_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(id) DO UPDATE SET
            fact = excluded.fact,
            updated_at = excluded.updated_at,
            source = excluded.source,
            confidence = excluded.confidence,
            trust_score = MAX(facts.trust_score, excluded.trust_score),
            active = 1
    """, (fact_id, fact, category, now, now, source, confidence, initial_trust_score))
    conn.commit()
    conn.close()

    log_with_context(logger, "info", "Fact stored",
                    fact_id=fact_id, category=category, trust_score=initial_trust_score,
                    fact_preview=fact[:50])
    return fact_id


def get_facts(
    category: str = None,
    query: str = None,
    limit: int = 20,
    include_inactive: bool = False,
    track_access: bool = True
) -> List[Dict[str, Any]]:
    """
    Retrieve stored facts.
    Optionally filter by category or search query.
    When track_access=True, increments access_count and boosts trust_score.
    """
    conn = _get_conn()

    sql = "SELECT * FROM facts WHERE 1=1"
    params = []

    if not include_inactive:
        sql += " AND active = 1"

    if category:
        sql += " AND category = ?"
        params.append(category)

    if query:
        sql += " AND fact LIKE ?"
        params.append(f"%{query}%")

    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    results = [dict(row) for row in rows]

    # Track access and boost trust for retrieved facts
    if track_access and results:
        now = datetime.now(ZURICH_TZ).isoformat(timespec="seconds")
        for fact in results:
            # Boost trust score: +0.1 per access, max 1.0
            new_trust = min(1.0, (fact.get("trust_score") or 0.0) + 0.1)
            new_count = (fact.get("access_count") or 0) + 1
            conn.execute("""
                UPDATE facts
                SET access_count = ?, trust_score = ?, last_accessed = ?
                WHERE id = ?
            """, (new_count, new_trust, now, fact["id"]))
        conn.commit()

    conn.close()

    return results


def deactivate_fact(fact_id: str) -> bool:
    """Mark a fact as inactive (soft delete)"""
    conn = _get_conn()
    cursor = conn.execute(
        "UPDATE facts SET active = 0, updated_at = ? WHERE id = ?",
        (datetime.now(ZURICH_TZ).isoformat(timespec="seconds"), fact_id)
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def add_entity(
    name: str,
    entity_type: str,
    description: str = None,
    metadata: dict = None
) -> str:
    """Add or update an entity (person, project, company)"""
    import json
    now = datetime.now(ZURICH_TZ).isoformat(timespec="seconds")
    entity_id = hashlib.sha256(f"{entity_type}::{name.lower()}".encode()).hexdigest()[:16]

    conn = _get_conn()
    conn.execute("""
        INSERT INTO entities (id, name, entity_type, description, created_at, updated_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            description = COALESCE(excluded.description, entities.description),
            updated_at = excluded.updated_at,
            metadata = excluded.metadata
    """, (entity_id, name, entity_type, description, now, now,
          json.dumps(metadata) if metadata else None))
    conn.commit()
    conn.close()

    log_with_context(logger, "info", "Entity stored",
                    entity_id=entity_id, entity_type=entity_type, name=name)
    return entity_id


def get_entities(
    entity_type: str = None,
    name_contains: str = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieve entities"""
    import json
    conn = _get_conn()

    sql = "SELECT * FROM entities WHERE 1=1"
    params = []

    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)

    if name_contains:
        sql += " AND name LIKE ?"
        params.append(f"%{name_contains}%")

    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        if d.get("metadata"):
            d["metadata"] = json.loads(d["metadata"])
        results.append(d)

    return results


def get_entity(entity_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific entity by ID"""
    import json
    conn = _get_conn()
    cursor = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        d = dict(row)
        if d.get("metadata"):
            d["metadata"] = json.loads(d["metadata"])
        return d
    return None


def add_relation(
    entity_id: str,
    related_entity_id: str,
    relation_type: str
) -> int:
    """Add a relationship between entities"""
    now = datetime.now(ZURICH_TZ).isoformat(timespec="seconds")
    conn = _get_conn()
    cursor = conn.execute("""
        INSERT INTO entity_relations (entity_id, related_entity_id, relation_type, created_at)
        VALUES (?, ?, ?, ?)
    """, (entity_id, related_entity_id, relation_type, now))
    conn.commit()
    relation_id = cursor.lastrowid
    conn.close()
    return relation_id


def get_memory_stats() -> Dict[str, Any]:
    """Get statistics about stored memory"""
    conn = _get_conn()

    facts_count = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE active = 1"
    ).fetchone()[0]

    facts_by_category = {}
    for row in conn.execute(
        "SELECT category, COUNT(*) as cnt FROM facts WHERE active = 1 GROUP BY category"
    ):
        facts_by_category[row["category"]] = row["cnt"]

    entities_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    entities_by_type = {}
    for row in conn.execute(
        "SELECT entity_type, COUNT(*) as cnt FROM entities GROUP BY entity_type"
    ):
        entities_by_type[row["entity_type"]] = row["cnt"]

    conn.close()

    return {
        "facts_total": facts_count,
        "facts_by_category": facts_by_category,
        "entities_total": entities_count,
        "entities_by_type": entities_by_type
    }


def get_trust_distribution() -> Dict[str, int]:
    """
    Get distribution of trust scores across all active facts.

    Categories based on cognitive science research on memory confidence:
    - high (>= 0.7): Well-proven facts, reliable for decisions
    - medium (0.4-0.7): Established facts with reasonable confidence
    - low (0.1-0.4): Less certain facts, may need reinforcement
    - minimal (< 0.1): New or decayed facts, treat with caution

    Returns:
        Dict with count for each trust level bucket
    """
    conn = _get_conn()

    distribution = {
        "high": 0,      # >= 0.7
        "medium": 0,    # 0.4 - 0.7
        "low": 0,       # 0.1 - 0.4
        "minimal": 0    # < 0.1
    }

    # Count facts in each trust bucket
    distribution["high"] = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE active = 1 AND trust_score >= 0.7"
    ).fetchone()[0]

    distribution["medium"] = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE active = 1 AND trust_score >= 0.4 AND trust_score < 0.7"
    ).fetchone()[0]

    distribution["low"] = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE active = 1 AND trust_score >= 0.1 AND trust_score < 0.4"
    ).fetchone()[0]

    distribution["minimal"] = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE active = 1 AND trust_score < 0.1"
    ).fetchone()[0]

    conn.close()

    return distribution


def get_mature_facts(
    min_trust_score: float = 0.5,
    min_access_count: int = 5,
    min_age_days: int = 7,
    exclude_migrated: bool = True
) -> List[Dict[str, Any]]:
    """
    Get facts that are mature enough for migration to permanent config/code.

    Criteria:
    - trust_score >= min_trust_score (built up through repeated access)
    - access_count >= min_access_count (used at least X times)
    - age >= min_age_days (has existed for some time)
    - not already migrated (unless exclude_migrated=False)
    """
    conn = _get_conn()

    cutoff_date = (datetime.now(ZURICH_TZ) - timedelta(days=min_age_days)).isoformat()

    sql = """
        SELECT * FROM facts
        WHERE active = 1
        AND trust_score >= ?
        AND access_count >= ?
        AND created_at <= ?
    """
    params = [min_trust_score, min_access_count, cutoff_date]

    if exclude_migrated:
        sql += " AND (migrated IS NULL OR migrated = 0)"

    sql += " ORDER BY trust_score DESC, access_count DESC"

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def mark_fact_migrated(fact_id: str, migration_target: str = None) -> bool:
    """
    Mark a fact as migrated to permanent storage.

    Args:
        fact_id: The fact ID
        migration_target: Where it was migrated to (e.g., "jarvis_permissions.yaml")
    """
    conn = _get_conn()
    now = datetime.now(ZURICH_TZ).isoformat(timespec="seconds")

    cursor = conn.execute("""
        UPDATE facts
        SET migrated = 1, updated_at = ?, source = COALESCE(source, '') || ' → migrated: ' || ?
        WHERE id = ?
    """, (now, migration_target or "config", fact_id))

    conn.commit()
    affected = cursor.rowcount
    conn.close()

    if affected > 0:
        log_with_context(logger, "info", "Fact marked as migrated",
                        fact_id=fact_id, target=migration_target)
    return affected > 0


def boost_trust(fact_id: str, amount: float = 0.2) -> bool:
    """
    Manually boost a fact's trust score.
    Used when user explicitly confirms a fact is correct.
    """
    conn = _get_conn()

    cursor = conn.execute("""
        UPDATE facts
        SET trust_score = MIN(1.0, COALESCE(trust_score, 0) + ?),
            updated_at = ?
        WHERE id = ? AND active = 1
    """, (amount, datetime.now(ZURICH_TZ).isoformat(timespec="seconds"), fact_id))

    conn.commit()
    affected = cursor.rowcount
    conn.close()

    return affected > 0


def reduce_trust(fact_id: str, amount: float = 0.3) -> bool:
    """
    Reduce a fact's trust score.
    Used when a fact turns out to be wrong or outdated.
    """
    conn = _get_conn()

    cursor = conn.execute("""
        UPDATE facts
        SET trust_score = MAX(0, COALESCE(trust_score, 0) - ?),
            updated_at = ?
        WHERE id = ? AND active = 1
    """, (amount, datetime.now(ZURICH_TZ).isoformat(timespec="seconds"), fact_id))

    conn.commit()
    affected = cursor.rowcount
    conn.close()

    return affected > 0


# Import timedelta for get_mature_facts and decay_facts
from datetime import timedelta
import math


def decay_facts(
    min_days_since_accessed: int = 14,
    decay_rate: float = 0.05,
    min_trust: float = 0.1,
    limit: int = 100,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Apply time-based decay to facts that haven't been accessed recently.

    Facts that haven't been accessed in `min_days_since_accessed` days
    will have their trust_score reduced using exponential decay.

    Half-life is approximately 60 days (slower than knowledge_items at 30 days).
    This is because facts represent "proven reliability" and should decay slower.

    Args:
        min_days_since_accessed: Only decay facts not accessed for this many days
        decay_rate: Decay rate per day (default 0.05 = ~60 day half-life)
        min_trust: Minimum trust score (floor, won't go below this)
        limit: Max facts to process per call
        dry_run: If True, don't actually update - just return what would change

    Returns:
        Dict with stats: {decayed: int, skipped: int, total_checked: int, details: [...]}
    """
    conn = _get_conn()
    now = datetime.now(ZURICH_TZ)
    cutoff = (now - timedelta(days=min_days_since_accessed)).isoformat()

    # Find facts that need decay:
    # - Active
    # - Has trust_score > min_trust (can still decay)
    # - last_accessed is NULL or older than cutoff
    cursor = conn.execute("""
        SELECT id, fact, category, trust_score, access_count, last_accessed, created_at
        FROM facts
        WHERE active = 1
        AND trust_score > ?
        AND (last_accessed IS NULL OR last_accessed < ?)
        ORDER BY trust_score DESC
        LIMIT ?
    """, (min_trust, cutoff, limit))

    rows = cursor.fetchall()
    facts_to_decay = [dict(row) for row in rows]

    decayed = 0
    skipped = 0
    details = []

    for fact in facts_to_decay:
        # Calculate days since last access (or creation if never accessed)
        last_access_str = fact.get("last_accessed") or fact.get("created_at")
        if last_access_str:
            try:
                last_access = datetime.fromisoformat(last_access_str.replace("Z", "+00:00").replace("+00:00", ""))
                days_inactive = (now - last_access).days
            except Exception as e:
                log_with_context(logger, "error", "Failed to parse last access datetime for fact decay", error=str(e), fact_id=fact.get("fact_id"), last_access_str=last_access_str)
                days_inactive = min_days_since_accessed  # Fallback
        else:
            days_inactive = min_days_since_accessed

        # Only decay if actually inactive long enough
        if days_inactive < min_days_since_accessed:
            skipped += 1
            continue

        # Calculate new trust using exponential decay
        current_trust = fact.get("trust_score") or 0.0
        # decay = e^(-rate * days)
        decay_factor = math.exp(-decay_rate * (days_inactive - min_days_since_accessed + 1))
        new_trust = max(min_trust, current_trust * decay_factor)

        # Skip if no meaningful change
        if abs(new_trust - current_trust) < 0.01:
            skipped += 1
            continue

        details.append({
            "id": fact["id"],
            "fact_preview": fact["fact"][:50],
            "category": fact["category"],
            "old_trust": round(current_trust, 3),
            "new_trust": round(new_trust, 3),
            "days_inactive": days_inactive
        })

        if not dry_run:
            conn.execute("""
                UPDATE facts
                SET trust_score = ?, updated_at = ?
                WHERE id = ?
            """, (new_trust, now.isoformat(timespec="seconds"), fact["id"]))
            decayed += 1
        else:
            decayed += 1  # Would have decayed

    if not dry_run:
        conn.commit()

    conn.close()

    log_with_context(logger, "info", "Fact decay completed",
                    decayed=decayed, skipped=skipped, total_checked=len(facts_to_decay),
                    dry_run=dry_run)

    return {
        "decayed": decayed,
        "skipped": skipped,
        "total_checked": len(facts_to_decay),
        "dry_run": dry_run,
        "details": details[:20]  # Limit details to avoid huge responses
    }


def get_fact_trust_scores(fact_ids: List[str] = None, limit: int = 100) -> Dict[str, float]:
    """
    Get trust scores for facts, for use in hybrid search ranking.

    Args:
        fact_ids: Optional list of specific fact IDs to fetch
        limit: Max facts to return (used if fact_ids not specified)

    Returns:
        Dict mapping fact_id -> trust_score
    """
    conn = _get_conn()

    if fact_ids:
        placeholders = ",".join("?" * len(fact_ids))
        cursor = conn.execute(f"""
            SELECT id, trust_score
            FROM facts
            WHERE active = 1 AND id IN ({placeholders})
        """, fact_ids)
    else:
        cursor = conn.execute("""
            SELECT id, trust_score
            FROM facts
            WHERE active = 1
            ORDER BY trust_score DESC
            LIMIT ?
        """, (limit,))

    results = {row["id"]: row["trust_score"] or 0.0 for row in cursor.fetchall()}
    conn.close()

    return results


def get_trust_score_distribution() -> Dict[str, int]:
    """
    Get distribution of trust scores across all active facts.
    Useful for monitoring memory health.

    Returns:
        Dict with counts per trust level:
        {high: count >= 0.7, medium: 0.4-0.7, low: 0.1-0.4, minimal: < 0.1}
    """
    conn = _get_conn()

    cursor = conn.execute("""
        SELECT
            SUM(CASE WHEN trust_score >= 0.7 THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN trust_score >= 0.4 AND trust_score < 0.7 THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN trust_score >= 0.1 AND trust_score < 0.4 THEN 1 ELSE 0 END) as low,
            SUM(CASE WHEN trust_score < 0.1 THEN 1 ELSE 0 END) as minimal,
            COUNT(*) as total
        FROM facts
        WHERE active = 1
    """)

    row = cursor.fetchone()
    conn.close()

    return {
        "high": row["high"] or 0,
        "medium": row["medium"] or 0,
        "low": row["low"] or 0,
        "minimal": row["minimal"] or 0,
        "total": row["total"] or 0
    }


# Initialize on import
init_db()
