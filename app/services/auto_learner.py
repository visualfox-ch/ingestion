"""
Auto-Learner Service - Phase 19.5

Automatically extracts and stores learnings from:
1. Successful tool executions
2. Query patterns that worked well
3. Error patterns to avoid

Stores to:
- facts table (semantic learnings)
- tool_usage table (execution stats)
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from threading import Lock

from ..observability import get_logger, log_with_context
from ..models import ScopeRef

logger = get_logger("jarvis.auto_learner")

# Database path
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
LEARNING_DB_PATH = BRAIN_ROOT / "system" / "state" / "jarvis_learning.db"

_db_lock = Lock()


def _scope_from_namespace(namespace: Optional[str]) -> tuple[str, str]:
    """Map legacy namespace to scope org/visibility for dual-write."""
    ns = namespace or "work_projektil"
    scope = ScopeRef.from_legacy_namespace(ns)
    return scope.org, scope.visibility


def _get_conn() -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    LEARNING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(LEARNING_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    # Create tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tool_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            query_intent TEXT,
            input_params TEXT,
            result_summary TEXT,
            success BOOLEAN NOT NULL,
            execution_ms INTEGER,
            user_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tool_usage_tool ON tool_usage(tool_name);
        CREATE INDEX IF NOT EXISTS idx_tool_usage_success ON tool_usage(success);
        CREATE INDEX IF NOT EXISTS idx_tool_usage_created ON tool_usage(created_at);

        CREATE TABLE IF NOT EXISTS query_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_pattern TEXT NOT NULL,
            tools_used TEXT NOT NULL,
            success BOOLEAN NOT NULL,
            feedback_score FLOAT,
            occurrence_count INTEGER DEFAULT 1,
            last_seen TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_query_pattern ON query_patterns(query_pattern);

        CREATE TABLE IF NOT EXISTS learned_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_type TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_value TEXT NOT NULL,
            confidence FLOAT DEFAULT 0.5,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(fact_type, fact_key)
        );

        CREATE INDEX IF NOT EXISTS idx_learned_facts_type ON learned_facts(fact_type);
    """)

    # Expand learned_facts schema for namespace->scope dual-write compatibility.
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(learned_facts)").fetchall()
    }
    if "namespace" not in cols:
        conn.execute("ALTER TABLE learned_facts ADD COLUMN namespace TEXT")
    if "scope_org" not in cols:
        conn.execute("ALTER TABLE learned_facts ADD COLUMN scope_org TEXT")
    if "scope_visibility" not in cols:
        conn.execute("ALTER TABLE learned_facts ADD COLUMN scope_visibility TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_facts_namespace ON learned_facts(namespace)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_facts_scope ON learned_facts(scope_org, scope_visibility)")
    conn.commit()
    return conn


def log_tool_usage(
    tool_name: str,
    input_params: Dict[str, Any],
    result_summary: str,
    success: bool,
    execution_ms: int = None,
    query_intent: str = None,
    user_id: str = None
) -> int:
    """
    Log a tool execution for analysis.

    Returns the row ID.
    """
    import json

    with _db_lock:
        try:
            conn = _get_conn()
            cursor = conn.execute("""
                INSERT INTO tool_usage
                (tool_name, query_intent, input_params, result_summary, success, execution_ms, user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tool_name,
                query_intent,
                json.dumps(input_params) if input_params else None,
                result_summary[:500] if result_summary else None,  # Truncate
                success,
                execution_ms,
                user_id,
                datetime.utcnow().isoformat()
            ))
            conn.commit()
            row_id = cursor.lastrowid
            conn.close()
            return row_id
        except Exception as e:
            log_with_context(logger, "warning", "Failed to log tool usage", error=str(e))
            return -1


def log_query_pattern(
    query_pattern: str,
    tools_used: List[str],
    success: bool,
    feedback_score: float = None
) -> None:
    """
    Log a query pattern (simplified intent) with the tools that worked.
    Updates occurrence count if pattern exists.
    """
    import json

    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()

            # Check if pattern exists
            cursor = conn.execute(
                "SELECT id, occurrence_count FROM query_patterns WHERE query_pattern = ?",
                (query_pattern,)
            )
            existing = cursor.fetchone()

            if existing:
                conn.execute("""
                    UPDATE query_patterns
                    SET occurrence_count = occurrence_count + 1,
                        last_seen = ?,
                        feedback_score = COALESCE(?, feedback_score)
                    WHERE id = ?
                """, (now, feedback_score, existing["id"]))
            else:
                conn.execute("""
                    INSERT INTO query_patterns
                    (query_pattern, tools_used, success, feedback_score, last_seen, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    query_pattern,
                    json.dumps(tools_used),
                    success,
                    feedback_score,
                    now, now
                ))

            conn.commit()
            conn.close()
        except Exception as e:
            log_with_context(logger, "warning", "Failed to log query pattern", error=str(e))


def store_learned_fact(
    fact_type: str,
    fact_key: str,
    fact_value: str,
    confidence: float = 0.5,
    source: str = "auto_learner",
    namespace: Optional[str] = None,
) -> bool:
    """
    Store a learned fact. Updates if exists with higher confidence.

    fact_type: jarvis_capability, tool_pattern, error_pattern, user_preference
    """
    with _db_lock:
        try:
            conn = _get_conn()
            now = datetime.utcnow().isoformat()
            resolved_namespace = namespace or "work_projektil"
            scope_org, scope_visibility = _scope_from_namespace(resolved_namespace)

            # Check if exists
            cursor = conn.execute(
                "SELECT id, confidence FROM learned_facts WHERE fact_type = ? AND fact_key = ?",
                (fact_type, fact_key)
            )
            existing = cursor.fetchone()

            if existing:
                # Only update if new confidence is higher
                if confidence > existing["confidence"]:
                    conn.execute("""
                        UPDATE learned_facts
                        SET fact_value = ?, confidence = ?, updated_at = ?,
                            namespace = ?, scope_org = ?, scope_visibility = ?
                        WHERE id = ?
                    """, (fact_value, confidence, now, resolved_namespace, scope_org, scope_visibility, existing["id"]))
            else:
                conn.execute("""
                    INSERT INTO learned_facts
                    (fact_type, fact_key, fact_value, confidence, source, namespace, scope_org, scope_visibility, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (fact_type, fact_key, fact_value, confidence, source, resolved_namespace, scope_org, scope_visibility, now, now))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log_with_context(logger, "warning", "Failed to store learned fact", error=str(e))
            return False


def get_tool_stats(days: int = 7) -> Dict[str, Any]:
    """Get tool usage statistics for the last N days."""
    try:
        conn = _get_conn()

        # Overall stats
        cursor = conn.execute("""
            SELECT
                tool_name,
                COUNT(*) as total_calls,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                AVG(execution_ms) as avg_ms
            FROM tool_usage
            WHERE created_at > datetime('now', ?)
            GROUP BY tool_name
            ORDER BY total_calls DESC
            LIMIT 20
        """, (f"-{days} days",))

        tools = []
        for row in cursor.fetchall():
            tools.append({
                "tool": row["tool_name"],
                "calls": row["total_calls"],
                "success_rate": row["successful"] / row["total_calls"] if row["total_calls"] > 0 else 0,
                "avg_ms": row["avg_ms"]
            })

        conn.close()
        return {"tools": tools, "period_days": days}
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get tool stats", error=str(e))
        return {"tools": [], "error": str(e)}


def get_learned_facts(fact_type: str = None, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
    """Get learned facts, optionally filtered by type and confidence."""
    try:
        conn = _get_conn()

        sql = "SELECT * FROM learned_facts WHERE confidence >= ?"
        params = [min_confidence]

        if fact_type:
            sql += " AND fact_type = ?"
            params.append(fact_type)

        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT 100"

        cursor = conn.execute(sql, params)
        facts = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return facts
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get learned facts", error=str(e))
        return []


def extract_learning_from_session(
    query: str,
    tool_calls: List[Dict[str, Any]],
    final_answer: str,
    success: bool,
    user_feedback: str = None,
    user_id: str = None,
    session_id: str = None,
    namespace: str = None,
    source: str = None,
) -> Dict[str, Any]:
    """
    Extract learnings from a completed session.
    Called after agent completes a query.

    Returns summary of what was learned.
    """
    learnings = {
        "tool_usage_logged": 0,
        "patterns_stored": 0,
        "facts_stored": 0,
        "context_mappings": 0
    }

    # 1. Log individual tool usage
    for tc in tool_calls:
        tool_success = tc.get("result_summary", "").lower() != "error"
        log_tool_usage(
            tool_name=tc.get("tool", "unknown"),
            input_params=tc.get("input", {}),
            result_summary=tc.get("result_summary", ""),
            success=tool_success,
            query_intent=query[:100],
            user_id=user_id,
        )
        learnings["tool_usage_logged"] += 1

    # 1b. Record context → tool mappings (Phase 1.2)
    try:
        from .context_tool_learner import get_context_tool_learner
        learner = get_context_tool_learner()
        for tc in tool_calls:
            tool_success = tc.get("result_summary", "").lower() != "error"
            result = learner.record_tool_success(
                query=query,
                tool_name=tc.get("tool", "unknown"),
                success=tool_success
            )
            if result.get("success"):
                learnings["context_mappings"] += result.get("recorded", 0)
    except Exception as ctx_err:
        log_with_context(logger, "debug", "Context learning failed", error=str(ctx_err))

    # 1c. Record session activity (Phase 1.3)
    try:
        from .session_pattern_service import get_session_pattern_service
        session_service = get_session_pattern_service()
        for tc in tool_calls:
            session_service.record_tool_use(
                tool_name=tc.get("tool", "unknown"),
                query=query
            )
        learnings["session_tracked"] = True
    except Exception as sess_err:
        log_with_context(logger, "debug", "Session tracking failed", error=str(sess_err))

    # 2. Extract query pattern
    if tool_calls:
        tools_used = [tc.get("tool", "unknown") for tc in tool_calls]
        # Simplified pattern: first 50 chars, lowercase, no special chars
        import re
        pattern = re.sub(r'[^a-z0-9\s]', '', query.lower()[:50]).strip()
        if pattern:
            log_query_pattern(
                query_pattern=pattern,
                tools_used=tools_used,
                success=success,
                feedback_score=1.0 if success else 0.0
            )
            learnings["patterns_stored"] += 1

    # 3. Store successful tool combinations as facts
    if success and len(tool_calls) >= 2:
        tools_combo = " + ".join(sorted(set(tc.get("tool") for tc in tool_calls if tc.get("tool"))))
        if len(tools_combo) > 5:
            store_learned_fact(
                fact_type="tool_pattern",
                fact_key=f"combo_{hash(tools_combo) % 100000}",
                fact_value=f"Tools [{tools_combo}] work well together for: {query[:50]}",
                confidence=0.6,
                source="session_success",
                namespace=namespace,
            )
            learnings["facts_stored"] += 1

    # ============ PHASE 4.1: AUTO-DECISION RECORDING ============
    # Record tool selection decisions automatically
    try:
        from .decision_tracker import get_decision_tracker
        tracker = get_decision_tracker()

        if tool_calls:
            # Record the tool selection decision
            tools_selected = [tc.get("tool", "unknown") for tc in tool_calls]
            decision_result = tracker.record_decision(
                category="tool_selection",
                decision_point=f"Tools for query: {query[:50]}",
                decision_made=", ".join(tools_selected[:3]),
                options_considered=tools_selected,
                reasoning="Auto-recorded from agent execution",
                confidence=0.7 if success else 0.4,
                context={
                    "query_length": len(query),
                    "tool_count": len(tool_calls),
                    "user_id": user_id,
                    "session_id": session_id,
                    "namespace": namespace,
                    "source": source or "agent",
                },
                query=query
            )

            # Record outcome
            if decision_result.get("success") and decision_result.get("decision_id"):
                tracker.record_outcome(
                    decision_id=decision_result["decision_id"],
                    outcome="success" if success else "partial",
                    outcome_score=1.0 if success else 0.5,
                    notes=f"Auto-recorded: {len(tool_calls)} tools used"
                )
                learnings["decisions_tracked"] = 1
    except Exception as dec_err:
        log_with_context(logger, "debug", "Decision tracking failed", error=str(dec_err))

    # ============ PHASE 4.2: AUTO-ROUTING FEEDBACK ============
    # Record routing outcomes for learning
    try:
        from .contextual_tool_router import get_contextual_tool_router
        router = get_contextual_tool_router()

        for tc in tool_calls:
            tool_success = tc.get("result_summary", "").lower() != "error"
            router.record_routing_outcome(
                query=query,
                tool_selected=tc.get("tool", "unknown"),
                was_successful=tool_success,
                context={"session_success": success}
            )
        learnings["routing_feedback"] = len(tool_calls)
    except Exception as route_err:
        log_with_context(logger, "debug", "Routing feedback failed", error=str(route_err))

    # ============ PHASE 4.3: AUTO-CHAIN RECORDING ============
    # Record tool chains when multiple tools are used
    try:
        if len(tool_calls) >= 2:
            from .smart_tool_chain_service import get_smart_tool_chain_service
            chain_service = get_smart_tool_chain_service()

            chain = [tc.get("tool", "unknown") for tc in tool_calls]
            chain_service.record_chain_usage(
                chain=chain,
                success=success
            )
            learnings["chain_recorded"] = True
    except Exception as chain_err:
        log_with_context(logger, "debug", "Chain recording failed", error=str(chain_err))

    return learnings


def get_tool_recommendations(query: str, top_n: int = 3) -> List[Dict[str, Any]]:
    """
    Get tool recommendations based on similar past queries.

    Returns list of recommended tools with confidence scores.
    """
    import json
    import re

    # Simplify query to pattern
    pattern = re.sub(r'[^a-z0-9\s]', '', query.lower()[:50]).strip()
    if not pattern:
        return []

    try:
        conn = _get_conn()

        # Find similar patterns (simple keyword matching)
        words = pattern.split()[:3]  # First 3 words
        if not words:
            return []

        # Build LIKE query for each word
        conditions = " OR ".join(["query_pattern LIKE ?" for _ in words])
        params = [f"%{w}%" for w in words]

        cursor = conn.execute(f"""
            SELECT tools_used, occurrence_count, feedback_score
            FROM query_patterns
            WHERE success = 1 AND ({conditions})
            ORDER BY occurrence_count DESC, feedback_score DESC
            LIMIT 10
        """, params)

        # Aggregate tool recommendations
        tool_scores = {}
        for row in cursor.fetchall():
            tools = json.loads(row["tools_used"])
            score = (row["occurrence_count"] or 1) * (row["feedback_score"] or 0.5)
            for tool in tools:
                if tool not in tool_scores:
                    tool_scores[tool] = {"tool": tool, "score": 0, "occurrences": 0}
                tool_scores[tool]["score"] += score
                tool_scores[tool]["occurrences"] += 1

        conn.close()

        # Sort by score and return top N
        recommendations = sorted(tool_scores.values(), key=lambda x: x["score"], reverse=True)[:top_n]
        return recommendations
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get tool recommendations", error=str(e))
        return []


def decay_old_facts(days_threshold: int = 14, decay_rate: float = 0.05) -> Dict[str, Any]:
    """
    Apply confidence decay to facts not updated recently.

    Facts older than days_threshold lose decay_rate confidence per run.
    Facts below 0.1 confidence are deleted.

    Returns summary of changes.
    """
    from datetime import timedelta

    try:
        conn = _get_conn()
        threshold_date = (datetime.utcnow() - timedelta(days=days_threshold)).isoformat()

        # Get facts to decay
        cursor = conn.execute("""
            SELECT id, fact_key, confidence
            FROM learned_facts
            WHERE updated_at < ?
        """, (threshold_date,))

        decayed = 0
        deleted = 0

        for row in cursor.fetchall():
            new_confidence = row["confidence"] - decay_rate

            if new_confidence < 0.1:
                conn.execute("DELETE FROM learned_facts WHERE id = ?", (row["id"],))
                deleted += 1
                log_with_context(logger, "debug", "Deleted low-confidence fact",
                               fact_key=row["fact_key"])
            else:
                conn.execute("""
                    UPDATE learned_facts
                    SET confidence = ?, updated_at = ?
                    WHERE id = ?
                """, (new_confidence, datetime.utcnow().isoformat(), row["id"]))
                decayed += 1

        conn.commit()
        conn.close()

        return {
            "decayed": decayed,
            "deleted": deleted,
            "threshold_days": days_threshold,
            "decay_rate": decay_rate
        }
    except Exception as e:
        log_with_context(logger, "warning", "Failed to decay facts", error=str(e))
        return {"error": str(e)}


def migrate_to_main_facts(min_confidence: float = 0.8, min_occurrences: int = 3) -> Dict[str, Any]:
    """
    Migrate high-confidence learned facts to the main facts system.

    This promotes "mature" learnings to the persistent facts table
    for long-term retention and use in prompts.

    Returns migration summary.
    """
    try:
        # Import main facts system
        from .. import memory_store

        conn = _get_conn()

        # Find mature facts (high confidence, multiple occurrences from patterns)
        cursor = conn.execute("""
            SELECT fact_type, fact_key, fact_value, confidence, source
            FROM learned_facts
            WHERE confidence >= ?
        """, (min_confidence,))

        migrated = 0
        skipped = 0

        for row in cursor.fetchall():
            try:
                # Map fact_type to memory_store category
                category_map = {
                    "tool_pattern": "jarvis_capability",
                    "jarvis_capability": "jarvis_capability",
                    "error_pattern": "jarvis_learning",
                    "user_preference": "preference"
                }
                category = category_map.get(row["fact_type"], "jarvis_learning")

                # Add to main facts with high trust score
                memory_store.add_fact(
                    fact=row["fact_value"],
                    category=category,
                    source=f"auto_learner:{row['source']}",
                    confidence=row["confidence"],
                    initial_trust_score=0.5  # Start with medium trust
                )

                # Mark as migrated by boosting confidence to 1.0
                conn.execute("""
                    UPDATE learned_facts
                    SET confidence = 1.0, source = 'migrated'
                    WHERE fact_key = ?
                """, (row["fact_key"],))

                migrated += 1
                log_with_context(logger, "info", "Migrated fact to main store",
                               fact_key=row["fact_key"], category=category)
            except Exception as e:
                log_with_context(logger, "warning", "Failed to migrate fact",
                               fact_key=row["fact_key"], error=str(e))
                skipped += 1

        conn.commit()
        conn.close()

        return {
            "migrated": migrated,
            "skipped": skipped,
            "min_confidence": min_confidence
        }
    except Exception as e:
        log_with_context(logger, "warning", "Failed to migrate facts", error=str(e))
        return {"error": str(e)}


def get_prompt_hints(query: str) -> str:
    """
    Generate prompt hints based on learned patterns.

    Called by prompt_assembler to inject relevant learnings.
    Returns formatted hint string or empty string.
    """
    hints = []

    # 1. Tool recommendations
    recommendations = get_tool_recommendations(query, top_n=3)
    if recommendations:
        tool_hints = ", ".join([f"{r['tool']} ({r['occurrences']}x erfolgreich)"
                               for r in recommendations])
        hints.append(f"Empfohlene Tools basierend auf ähnlichen Anfragen: {tool_hints}")

    # 2. Relevant learned facts
    try:
        facts = get_learned_facts(min_confidence=0.6)
        relevant_facts = []
        query_lower = query.lower()

        for fact in facts[:10]:  # Check top 10 by confidence
            # Simple relevance check
            if any(word in fact["fact_value"].lower() for word in query_lower.split()[:3]):
                relevant_facts.append(fact["fact_value"])

        if relevant_facts:
            hints.append(f"Gelernte Patterns: {'; '.join(relevant_facts[:2])}")
    except Exception:
        pass

    if hints:
        return "\n## Auto-Learning Hints\n" + "\n".join(f"- {h}" for h in hints)
    return ""
