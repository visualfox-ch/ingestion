"""
Unified State Management with PostgreSQL

Consolidates state from SQLite (ingest_state.db) and JSON files (connector_state)
into a single PostgreSQL database for consistency and reliability.

Phase 11: Memory Consolidation & Ranking
"""
import os
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from .observability import get_logger, log_with_context
from .connection_pool_metrics import get_pool_metrics

logger = get_logger("jarvis.postgres_state")


def _scope_from_namespace(namespace: Optional[str]) -> tuple[str, str]:
    """Map legacy namespace to scope fields for dual-write migrations."""
    mapping = {
        "private": ("personal", "private"),
        "work_projektil": ("projektil", "internal"),
        "work_visualfox": ("visualfox", "internal"),
        "shared": ("personal", "shared"),
    }
    return mapping.get(namespace or "work_projektil", ("projektil", "internal"))

# Database connection config
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "jarvis")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "jarvis")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

_pool = None
_pool_lock = threading.Lock()


def _init_pool() -> None:
    """Initialize the shared ThreadedConnectionPool if needed."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg2 import pool
                # Get pool size from environment (default: 5-75)
                pool_min = int(os.environ.get("DB_POOL_MIN", "5"))
                pool_max = int(os.environ.get("DB_POOL_MAX", "75"))
                _pool = pool.ThreadedConnectionPool(
                    minconn=pool_min,
                    maxconn=pool_max,
                    host=POSTGRES_HOST,
                    port=POSTGRES_PORT,
                    database=POSTGRES_DB,
                    user=POSTGRES_USER,
                    password=POSTGRES_PASSWORD,
                    cursor_factory=RealDictCursor
                )


def get_pool():
    """Return the shared ThreadedConnectionPool (lazy-initialized)."""
    _init_pool()
    return _pool


@contextmanager
def get_conn():
    """Get a database connection with RealDictCursor (context manager with guaranteed cleanup)."""
    _init_pool()
    metrics = get_pool_metrics("postgres_state")
    
    # Track acquisition time
    start_time = datetime.now().timestamp()
    conn = _pool.getconn()
    wait_time = datetime.now().timestamp() - start_time
    metrics.record_acquisition(wait_time)
    
    try:
        used = len(getattr(_pool, "_used", {}) or {})
        available = len(getattr(_pool, "_pool", []) or [])
        metrics.record_pool_state(total=used + available, in_use=used, available=available)
    except Exception:
        pass
    
    if wait_time > 0.1:  # Log if waiting >100ms
        log_with_context(logger, "warning", "Slow pool acquisition", 
                       wait_time_ms=int(wait_time * 1000))
    
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
        metrics.record_release()
        try:
            used = len(getattr(_pool, "_used", {}) or {})
            available = len(getattr(_pool, "_pool", []) or [])
            metrics.record_pool_state(total=used + available, in_use=used, available=available)
        except Exception:
            pass


def put_conn(conn):
    """DEPRECATED: Use get_conn() as context manager instead.
    
    This function is kept for backward compatibility only.
    New code should use: with get_conn() as conn: ...
    """
    if conn and _pool:
        _pool.putconn(conn)
        metrics = get_pool_metrics("postgres_state")
        metrics.record_release()


def close_pool():
    """Close all connections in the pool (shutdown handler)"""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


@contextmanager
def get_cursor():
    """Context manager for database cursor with auto-commit"""
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                timeout_ms = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))
                cur.execute(f"SET statement_timeout = {timeout_ms}")
                yield cur
                conn.commit()
        except Exception:
            conn.rollback()
            raise


# ============ Schema Initialization ============

def init_state_schema():
    """Initialize all state tables in PostgreSQL"""
    with get_cursor() as cur:
        # Connector State Table (replaces JSON files)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS connector_state (
                connector_id TEXT PRIMARY KEY,
                connector_type TEXT NOT NULL,
                namespace TEXT NOT NULL,

                -- Sync cursor/pagination
                last_sync_cursor TEXT,
                last_sync_ts TIMESTAMP,

                -- Health tracking
                enabled BOOLEAN DEFAULT TRUE,
                consecutive_errors INTEGER DEFAULT 0,
                last_error TEXT,
                last_error_ts TIMESTAMP,

                -- Metrics
                total_items_synced INTEGER DEFAULT 0,
                total_errors INTEGER DEFAULT 0,

                -- Configuration (JSON)
                config JSONB DEFAULT '{}',

                -- Sync history (last 10 runs)
                sync_history JSONB DEFAULT '[]',

                -- Metadata
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Sync Run Table (detailed sync logs)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_run (
                id SERIAL PRIMARY KEY,
                connector_id TEXT NOT NULL REFERENCES connector_state(connector_id),
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                status TEXT DEFAULT 'running',
                items_processed INTEGER DEFAULT 0,
                items_skipped INTEGER DEFAULT 0,
                items_errored INTEGER DEFAULT 0,
                error_message TEXT,
                cursor_before TEXT,
                cursor_after TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sync_run_connector
            ON sync_run(connector_id, started_at DESC)
        """)

        # Ingest Event Table (replaces ingest_log in SQLite)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ingest_event (
                id SERIAL PRIMARY KEY,
                source_path TEXT NOT NULL,
                namespace TEXT NOT NULL,
                ingest_type TEXT NOT NULL,
                ingest_ts TIMESTAMP NOT NULL,
                chunks_upserted INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_msg TEXT,

                -- Dedupe
                UNIQUE(source_path, ingest_type),

                -- Indexes
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ingest_source ON ingest_event(source_path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ingest_namespace ON ingest_event(namespace, ingest_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ingest_status ON ingest_event(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ingest_ts ON ingest_event(ingest_ts DESC)")

        # Conversations Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversation (
                session_id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                title TEXT,
                message_count INTEGER DEFAULT 0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_conv_namespace ON conversation(namespace)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversation(updated_at DESC)")

        # Messages Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES conversation(session_id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                tokens_in INTEGER,
                tokens_out INTEGER,
                sources JSONB,
                source TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_session ON message(session_id, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_source ON message(source)")

        # Migration: Add source column if it doesn't exist (for existing databases)
        cur.execute("""
            ALTER TABLE message ADD COLUMN IF NOT EXISTS source TEXT
        """)

        # Telegram Users Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS telegram_user (
                user_id BIGINT PRIMARY KEY,
                session_id TEXT,
                namespace TEXT DEFAULT 'work_projektil',
                role TEXT DEFAULT 'assistant',
                updated_at TIMESTAMP NOT NULL
            )
        """)

        # Working State Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS working_state (
                id TEXT PRIMARY KEY DEFAULT 'default',
                active_threads JSONB DEFAULT '[]',
                open_questions JSONB DEFAULT '[]',
                partial_results JSONB DEFAULT '{}',
                resume_hint TEXT,
                momentum TEXT DEFAULT 'cold',
                updated_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
        """)

        # Active Context Buffer Table (ADHD optimization - max 5 threads)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS active_context_buffer (
                id TEXT PRIMARY KEY,
                state_id TEXT DEFAULT 'default',
                title TEXT NOT NULL,
                context_summary TEXT,
                priority INTEGER DEFAULT 3 CHECK (priority >= 1 AND priority <= 5),
                status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'evicted')),
                thread_type TEXT DEFAULT 'task',
                metadata JSONB DEFAULT '{}',
                added_at TIMESTAMP NOT NULL,
                last_touched_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                evicted_reason TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_acb_state ON active_context_buffer(state_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_acb_status ON active_context_buffer(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_acb_priority ON active_context_buffer(priority DESC)")

        # System Capability Updates Table (Claude Code → Jarvis sync)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_capability_update (
                id SERIAL PRIMARY KEY,
                update_type TEXT NOT NULL CHECK (update_type IN ('capability', 'feature', 'fix', 'behavior')),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT DEFAULT 'claude_code',
                version TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scu_created ON system_capability_update(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scu_type ON system_capability_update(update_type)")

        # Alert Deduplication Cache (persists across restarts)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alert_sent_cache (
                email_id TEXT PRIMARY KEY,
                sent_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_asc_sent ON alert_sent_cache(sent_at)")

        # Decision Outcome Table (Phase 12.3: Salience Signals)
        # Tracks outcomes of decisions that used knowledge items
        cur.execute("""
            CREATE TABLE IF NOT EXISTS decision_outcome (
                id SERIAL PRIMARY KEY,
                decision_id TEXT NOT NULL,
                knowledge_item_ids JSONB DEFAULT '[]',
                outcome_rating INTEGER CHECK (outcome_rating >= 1 AND outcome_rating <= 10),
                outcome_notes TEXT,
                decision_context TEXT,
                decision_type TEXT DEFAULT 'general',
                user_id INTEGER,
                recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(decision_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_do_recorded ON decision_outcome(recorded_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_do_rating ON decision_outcome(outcome_rating)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_do_type ON decision_outcome(decision_type)")

        # Knowledge Item Salience Table (Phase 12.3)
        # Stores calculated salience scores for knowledge items
        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_salience (
                knowledge_item_id TEXT PRIMARY KEY,
                decision_impact FLOAT DEFAULT 0.0,
                goal_relevance FLOAT DEFAULT 0.0,
                surprise_factor FLOAT DEFAULT 0.0,
                salience_score FLOAT DEFAULT 0.0,
                positive_outcomes INTEGER DEFAULT 0,
                negative_outcomes INTEGER DEFAULT 0,
                last_used_in_decision TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ks_salience ON knowledge_salience(salience_score DESC)")

        # Profile Staging Table (Phase 15: Profile Ingestion with Approval)
        # Stores uploaded profiles pending review before merging into knowledge
        cur.execute("""
            CREATE TABLE IF NOT EXISTS profile_staging (
                id SERIAL PRIMARY KEY,
                profile_data JSONB NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual_upload',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'merged')),
                target_person_id TEXT,
                comparison_results JSONB DEFAULT '{}',
                approval_notes TEXT,
                confidence_score FLOAT DEFAULT 0.5,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                reviewed_by TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_status ON profile_staging(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_created ON profile_staging(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_target ON profile_staging(target_person_id)")

        # ============ Phase 17: Person Intelligence Tables ============

        # User Behavioral Baseline - stores statistical expectations for user behavior
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_behavioral_baseline (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,

                -- Metric identification
                metric_category TEXT NOT NULL,
                metric_name TEXT NOT NULL,

                -- Statistical values
                expected_value FLOAT NOT NULL,
                std_dev FLOAT DEFAULT 0.0,
                min_observed FLOAT,
                max_observed FLOAT,

                -- Confidence tracking
                sample_count INTEGER DEFAULT 0,
                confidence FLOAT DEFAULT 0.0,

                -- Context filter (optional)
                context_filter JSONB DEFAULT '{}',

                -- Timestamps
                last_updated TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),

                UNIQUE(user_id, metric_category, metric_name, context_filter)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ubb_user ON user_behavioral_baseline(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ubb_category ON user_behavioral_baseline(metric_category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ubb_confidence ON user_behavioral_baseline(confidence DESC)")

        # User Preferences - stores learned preferences with context
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,

                -- Preference identification
                preference_category TEXT NOT NULL,
                preference_key TEXT NOT NULL,

                -- Value (flexible JSONB)
                preference_value JSONB NOT NULL,

                -- Context (optional - for person/domain-specific prefs)
                context_type TEXT,
                context_id TEXT,

                -- Learning metadata
                confidence FLOAT DEFAULT 0.5,
                learned_from TEXT DEFAULT 'inferred',
                positive_signals INTEGER DEFAULT 0,
                negative_signals INTEGER DEFAULT 0,

                -- Timestamps
                last_used TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

                UNIQUE(user_id, preference_category, preference_key, context_type, context_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_up_user ON user_preferences(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_up_category ON user_preferences(preference_category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_up_context ON user_preferences(context_type, context_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_up_confidence ON user_preferences(confidence DESC)")

        # Active Learning Queue - stores questions Jarvis wants to ask
        cur.execute("""
            CREATE TABLE IF NOT EXISTS active_learning_queue (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,

                -- Question details
                question_type TEXT NOT NULL,
                question_text TEXT NOT NULL,
                options JSONB DEFAULT '[]',

                -- State
                status TEXT DEFAULT 'pending',
                priority FLOAT DEFAULT 0.5,

                -- Targeting
                target_preference_key TEXT,
                uncertainty_reason TEXT,

                -- Answer
                answer_value JSONB,
                answered_at TIMESTAMP,

                -- Lifecycle
                asked_at TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alq_user_status ON active_learning_queue(user_id, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alq_priority ON active_learning_queue(priority DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alq_expires ON active_learning_queue(expires_at)")

        # User Anomaly Log - stores detected anomalies for review
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_anomaly_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                baseline_id INTEGER REFERENCES user_behavioral_baseline(id),

                -- Anomaly data
                observed_value FLOAT NOT NULL,
                expected_value FLOAT NOT NULL,
                std_dev FLOAT NOT NULL,
                deviation_score FLOAT NOT NULL,

                anomaly_type TEXT,
                severity TEXT DEFAULT 'normal',

                -- Context
                context_snapshot JSONB DEFAULT '{}',

                -- Resolution
                status TEXT DEFAULT 'open',
                explanation TEXT,
                resolved_at TIMESTAMP,

                -- Notification
                notification_sent BOOLEAN DEFAULT FALSE,
                notification_sent_at TIMESTAMP,

                detected_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ual_user_status ON user_anomaly_log(user_id, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ual_severity ON user_anomaly_log(severity)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ual_detected ON user_anomaly_log(detected_at DESC)")

        # ============ Phase 17.2: Preference Learning Tables ============

        # User Communication Profiles - style preferences (formal/casual, length, tone)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_communication_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,

                -- Style metrics
                formality_score FLOAT DEFAULT 0.5,
                avg_message_length FLOAT DEFAULT 0.0,
                emoji_ratio FLOAT DEFAULT 0.0,
                abbreviation_ratio FLOAT DEFAULT 0.0,
                exclamation_frequency FLOAT DEFAULT 0.0,
                punctuation_precision FLOAT DEFAULT 0.5,

                -- Greeting patterns (Jarvis-refined)
                greeting_formality FLOAT DEFAULT 0.5,
                uses_sie_form BOOLEAN DEFAULT FALSE,

                -- Confidence
                sample_count INTEGER DEFAULT 0,
                confidence FLOAT DEFAULT 0.0,

                -- Timestamps
                last_updated TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),

                UNIQUE(user_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ucp_user ON user_communication_profiles(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ucp_confidence ON user_communication_profiles(confidence DESC)")

        # User Context Preferences - context-specific style rules
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_context_preferences (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,

                -- Context type
                context_type TEXT NOT NULL,

                -- Style overrides for this context
                formality_modifier FLOAT DEFAULT 0.0,
                length_modifier FLOAT DEFAULT 0.0,
                urgency_threshold FLOAT DEFAULT 0.5,

                -- Detection rules (Jarvis-refined)
                is_internal_domain BOOLEAN DEFAULT FALSE,
                reply_thread_threshold INTEGER DEFAULT 3,

                -- Learning
                sample_count INTEGER DEFAULT 0,
                confidence FLOAT DEFAULT 0.0,
                last_applied TIMESTAMP,

                -- Timestamps
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

                UNIQUE(user_id, context_type)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ucxp_user ON user_context_preferences(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ucxp_context ON user_context_preferences(context_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ucxp_confidence ON user_context_preferences(confidence DESC)")

        # Interaction Patterns - person-specific communication patterns
        cur.execute("""
            CREATE TABLE IF NOT EXISTS interaction_patterns (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,

                -- Person identification
                person_email TEXT NOT NULL,
                person_name TEXT,
                person_domain TEXT,

                -- Communication style with this person
                formality_score FLOAT DEFAULT 0.5,
                avg_response_time_hours FLOAT,
                typical_message_length FLOAT,

                -- Relationship signals
                is_internal BOOLEAN DEFAULT FALSE,
                interaction_count INTEGER DEFAULT 0,
                last_interaction TIMESTAMP,

                -- Confidence
                confidence FLOAT DEFAULT 0.0,

                -- Timestamps
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

                UNIQUE(user_id, person_email)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ip_user ON interaction_patterns(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ip_person ON interaction_patterns(person_email)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ip_domain ON interaction_patterns(person_domain)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ip_confidence ON interaction_patterns(confidence DESC)")

        # Phase 18: Cross-AI Learning - Session Learnings Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_session_learnings (
                id SERIAL PRIMARY KEY,
                session_id TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,  -- claude_code, copilot, cursor, other
                summary TEXT,
                files_modified JSONB DEFAULT '[]',
                learnings JSONB DEFAULT '[]',  -- [{fact, category, confidence}]
                code_changes JSONB DEFAULT '{}',  -- {added_lines, removed_lines, files}
                duration_minutes INTEGER,
                processed BOOLEAN DEFAULT FALSE,
                facts_extracted INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                processed_at TIMESTAMPTZ
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_asl_source ON ai_session_learnings(source)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_asl_processed ON ai_session_learnings(processed)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_asl_created ON ai_session_learnings(created_at DESC)")

        # Phase 18: Workflow Runs Table (for n8n workflow idempotency + logging)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id SERIAL PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                workflow_name TEXT NOT NULL,
                status TEXT DEFAULT 'running',  -- running, success, partial, failed
                result_counts JSONB DEFAULT '{}',
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wr_workflow ON workflow_runs(workflow_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wr_status ON workflow_runs(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wr_created ON workflow_runs(created_at DESC)")

        # Gate A: n8n Dead Letter Queue (for retry + error tracking)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS n8n_dead_letter (
                dl_id SERIAL PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                execution_id TEXT,
                error_type TEXT,
                error_message TEXT,
                payload JSONB DEFAULT '{}',
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                status TEXT DEFAULT 'pending',  -- pending, retrying, resolved, abandoned
                resolved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dl_workflow ON n8n_dead_letter(workflow_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dl_status ON n8n_dead_letter(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dl_created ON n8n_dead_letter(created_at DESC)")

        # Phase 18: Permission Matrix (Gate A) - policy-as-data
        cur.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                permission_id SERIAL PRIMARY KEY,
                action TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL,
                description TEXT,
                requires_approval BOOLEAN DEFAULT false,
                notify_user BOOLEAN DEFAULT false,
                timeout_hours INTEGER,
                guidelines JSONB DEFAULT '[]',
                reason TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_perm_action ON permissions(action)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_perm_tier ON permissions(tier)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS permission_audit (
                audit_id SERIAL PRIMARY KEY,
                action TEXT NOT NULL,
                actor TEXT,
                tier TEXT,
                result TEXT,
                context JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_perm_audit_action ON permission_audit(action)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_perm_audit_created ON permission_audit(created_at DESC)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sandbox_paths (
                path_id SERIAL PRIMARY KEY,
                path TEXT NOT NULL,
                path_type TEXT NOT NULL,
                permissions JSONB DEFAULT '[]',
                description TEXT,
                reason TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sandbox_type ON sandbox_paths(path_type)")

        # Tool execution audit trail (Gate A)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tool_audit (
                audit_id SERIAL PRIMARY KEY,
                trace_id TEXT,
                actor TEXT DEFAULT 'jarvis',
                tool_name TEXT NOT NULL,
                tool_input JSONB DEFAULT '{}',
                tool_output JSONB DEFAULT '{}',
                reason TEXT,
                duration_ms INTEGER,
                success BOOLEAN DEFAULT true,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_trace ON tool_audit(trace_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_tool ON tool_audit(tool_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_created ON tool_audit(created_at DESC)")

        log_with_context(logger, "info", "PostgreSQL state schema initialized")


# ============ Connector State Functions ============

def get_connector_state(connector_id: str) -> Optional[Dict]:
    """Get connector state from Postgres"""
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM connector_state WHERE connector_id = %s
        """, (connector_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_connector_state(
    connector_id: str,
    connector_type: str,
    namespace: str,
    **kwargs
) -> bool:
    """Create or update connector state"""
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO connector_state
            (connector_id, connector_type, namespace, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (connector_id) DO UPDATE SET
                connector_type = EXCLUDED.connector_type,
                namespace = EXCLUDED.namespace,
                updated_at = EXCLUDED.updated_at
            RETURNING connector_id
        """, (connector_id, connector_type, namespace, now, now))

        # Update additional fields if provided
        if kwargs:
            updates = []
            params = []
            for key, value in kwargs.items():
                if key in ('last_sync_cursor', 'last_sync_ts', 'enabled',
                          'consecutive_errors', 'last_error', 'last_error_ts',
                          'total_items_synced', 'total_errors', 'config', 'sync_history'):
                    updates.append(f"{key} = %s")
                    if key in ('config', 'sync_history'):
                        params.append(json.dumps(value) if isinstance(value, (dict, list)) else value)
                    else:
                        params.append(value)

            if updates:
                params.append(connector_id)
                cur.execute(f"""
                    UPDATE connector_state
                    SET {', '.join(updates)}, updated_at = NOW()
                    WHERE connector_id = %s
                """, params)

        return True


def update_connector_sync(
    connector_id: str,
    status: str,
    items_processed: int = 0,
    new_cursor: str = None,
    error_message: str = None
):
    """Update connector after sync completion"""
    now = datetime.now()

    with get_cursor() as cur:
        if status == "success":
            cur.execute("""
                UPDATE connector_state SET
                    last_sync_ts = %s,
                    last_sync_cursor = COALESCE(%s, last_sync_cursor),
                    consecutive_errors = 0,
                    total_items_synced = total_items_synced + %s,
                    updated_at = %s
                WHERE connector_id = %s
            """, (now, new_cursor, items_processed, now, connector_id))
        else:
            cur.execute("""
                UPDATE connector_state SET
                    last_sync_ts = %s,
                    consecutive_errors = consecutive_errors + 1,
                    total_errors = total_errors + 1,
                    last_error = %s,
                    last_error_ts = %s,
                    updated_at = %s
                WHERE connector_id = %s
            """, (now, error_message, now, now, connector_id))


def list_connectors() -> List[Dict]:
    """List all connectors with health status"""
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                connector_id, connector_type, namespace, enabled,
                last_sync_ts, consecutive_errors, total_items_synced,
                CASE
                    WHEN NOT enabled THEN 'disabled'
                    WHEN consecutive_errors >= 5 THEN 'unhealthy'
                    WHEN consecutive_errors >= 2 THEN 'degraded'
                    WHEN last_sync_ts IS NULL THEN 'never_synced'
                    ELSE 'healthy'
                END as health
            FROM connector_state
            ORDER BY connector_type, namespace
        """)
        return [dict(row) for row in cur.fetchall()]


# ============ Ingest Event Functions ============

def record_ingest(
    source_path: str,
    namespace: str,
    ingest_type: str,
    ingest_ts: str,
    chunks_upserted: int,
    status: str = "success",
    error_msg: str = None
):
    """Record an ingest event (upsert)"""
    scope_org, scope_visibility = _scope_from_namespace(namespace)
    with get_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO ingest_event
                (source_path, namespace, scope_org, scope_visibility, ingest_type, ingest_ts, chunks_upserted, status, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_path, ingest_type) DO UPDATE SET
                    namespace = EXCLUDED.namespace,
                    scope_org = EXCLUDED.scope_org,
                    scope_visibility = EXCLUDED.scope_visibility,
                    ingest_ts = EXCLUDED.ingest_ts,
                    chunks_upserted = EXCLUDED.chunks_upserted,
                    status = EXCLUDED.status,
                    error_msg = EXCLUDED.error_msg
            """, (
                source_path,
                namespace,
                scope_org,
                scope_visibility,
                ingest_type,
                ingest_ts,
                chunks_upserted,
                status,
                error_msg,
            ))
        except Exception as e:
            # Backward compatibility for environments where scope columns are not present yet.
            if "scope_org" not in str(e) and "scope_visibility" not in str(e):
                raise
            cur.execute("""
                INSERT INTO ingest_event
                (source_path, namespace, ingest_type, ingest_ts, chunks_upserted, status, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_path, ingest_type) DO UPDATE SET
                    ingest_ts = EXCLUDED.ingest_ts,
                    chunks_upserted = EXCLUDED.chunks_upserted,
                    status = EXCLUDED.status,
                    error_msg = EXCLUDED.error_msg
            """, (source_path, namespace, ingest_type, ingest_ts, chunks_upserted, status, error_msg))


def is_already_ingested(source_path: str, ingest_type: str) -> bool:
    """Check if source was successfully ingested"""
    with get_cursor() as cur:
        cur.execute("""
            SELECT status FROM ingest_event
            WHERE source_path = %s AND ingest_type = %s
            LIMIT 1
        """, (source_path, ingest_type))
        row = cur.fetchone()
        return row and row["status"] == "success"


def get_ingest_history(
    namespace: str = None,
    ingest_type: str = None,
    status: str = None,
    limit: int = 100
) -> List[Dict]:
    """Query ingest history with filters"""
    with get_cursor() as cur:
        conditions = ["1=1"]
        params = []

        if namespace:
            conditions.append("namespace = %s")
            params.append(namespace)
        if ingest_type:
            conditions.append("ingest_type = %s")
            params.append(ingest_type)
        if status:
            conditions.append("status = %s")
            params.append(status)

        params.append(limit)

        cur.execute(f"""
            SELECT * FROM ingest_event
            WHERE {' AND '.join(conditions)}
            ORDER BY ingest_ts DESC
            LIMIT %s
        """, params)

        return [dict(row) for row in cur.fetchall()]


def get_ingest_stats() -> Dict:
    """Get aggregate ingest statistics"""
    with get_cursor() as cur:
        # By type
        cur.execute("""
            SELECT ingest_type, COUNT(*) as count, SUM(chunks_upserted) as total_chunks
            FROM ingest_event
            WHERE status = 'success'
            GROUP BY ingest_type
        """)
        by_type = {row["ingest_type"]: {"count": row["count"], "total_chunks": row["total_chunks"] or 0}
                   for row in cur.fetchall()}

        # Recent errors
        cur.execute("""
            SELECT COUNT(*) as error_count
            FROM ingest_event
            WHERE status = 'error'
            AND ingest_ts > NOW() - INTERVAL '7 days'
        """)
        error_count = cur.fetchone()["error_count"]

        # Last success per type
        cur.execute("""
            SELECT ingest_type, MAX(ingest_ts) as last_ingest_ts
            FROM ingest_event
            WHERE status = 'success'
            GROUP BY ingest_type
        """)
        last_success = {row["ingest_type"]: str(row["last_ingest_ts"]) for row in cur.fetchall()}

        return {
            "by_type": by_type,
            "error_count_7d": error_count,
            "last_success": last_success
        }


# ============ Conversation Functions ============

def create_session(session_id: str, namespace: str) -> str:
    """Create a new conversation session"""
    now = datetime.now()
    scope_org, scope_visibility = _scope_from_namespace(namespace)
    with get_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO conversation (session_id, namespace, scope_org, scope_visibility, created_at, updated_at, message_count)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
                ON CONFLICT (session_id) DO NOTHING
            """, (session_id, namespace, scope_org, scope_visibility, now, now))
        except Exception as e:
            if "scope_org" not in str(e) and "scope_visibility" not in str(e):
                raise
            cur.execute("""
                INSERT INTO conversation (session_id, namespace, created_at, updated_at, message_count)
                VALUES (%s, %s, %s, %s, 0)
                ON CONFLICT (session_id) DO NOTHING
            """, (session_id, namespace, now, now))
    return session_id


def add_message(
    session_id: str,
    role: str,
    content: str,
    tokens_in: int = None,
    tokens_out: int = None,
    sources: List[str] = None,
    source: str = None
):
    """Add a message to a conversation

    Args:
        source: Origin of message (telegram, claude_code, copilot, api, etc.)
    """
    now = datetime.now()
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO message (session_id, role, content, created_at, tokens_in, tokens_out, sources, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (session_id, role, content, now, tokens_in, tokens_out,
              json.dumps(sources) if sources else None, source))

        cur.execute("""
            UPDATE conversation
            SET updated_at = %s, message_count = message_count + 1
            WHERE session_id = %s
        """, (now, session_id))


def get_conversation_history(session_id: str, limit: int = 20) -> List[Dict]:
    """Get recent messages from a conversation"""
    with get_cursor() as cur:
        cur.execute("""
            SELECT role, content, created_at, tokens_in, tokens_out, sources
            FROM message
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (session_id, limit))

        rows = cur.fetchall()
        messages = []
        for row in reversed(rows):
            msg = {
                "role": row["role"],
                "content": row["content"],
                "created_at": str(row["created_at"])
            }
            if row["sources"]:
                msg["sources"] = row["sources"]
            messages.append(msg)

        return messages


# ============ Telegram User Functions ============

def get_telegram_user_state(user_id: int) -> Optional[Dict]:
    """Get telegram user's session state"""
    with get_cursor() as cur:
        cur.execute("""
            SELECT session_id, namespace, role FROM telegram_user WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def set_telegram_user_state(
    user_id: int,
    session_id: str = None,
    namespace: str = None,
    role: str = None
):
    """Update telegram user's state (upsert)"""
    now = datetime.now()
    ns_value = namespace or "work_projektil"
    default_org, default_visibility = _scope_from_namespace(ns_value)
    with get_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO telegram_user (user_id, session_id, namespace, default_org, default_visibility, role, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    session_id = COALESCE(%s, telegram_user.session_id),
                    namespace = COALESCE(%s, telegram_user.namespace),
                    default_org = COALESCE(%s, telegram_user.default_org),
                    default_visibility = COALESCE(%s, telegram_user.default_visibility),
                    role = COALESCE(%s, telegram_user.role),
                    updated_at = %s
            """, (
                user_id,
                session_id,
                ns_value,
                default_org,
                default_visibility,
                role or "assistant",
                now,
                session_id,
                namespace,
                default_org if namespace is not None else None,
                default_visibility if namespace is not None else None,
                role,
                now,
            ))
        except Exception as e:
            if "default_org" not in str(e) and "default_visibility" not in str(e):
                raise
            cur.execute("""
                INSERT INTO telegram_user (user_id, session_id, namespace, role, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    session_id = COALESCE(%s, telegram_user.session_id),
                    namespace = COALESCE(%s, telegram_user.namespace),
                    role = COALESCE(%s, telegram_user.role),
                    updated_at = %s
            """, (user_id, session_id, ns_value, role or 'assistant', now,
                  session_id, namespace, role, now))


def get_all_telegram_users() -> List[Dict]:
    """Get all registered telegram users"""
    with get_cursor() as cur:
        cur.execute("SELECT user_id, namespace FROM telegram_user")
        return [dict(row) for row in cur.fetchall()]


# ============ Working State Functions ============

def get_working_state(state_id: str = "default") -> Optional[Dict]:
    """Get current working state for session continuity"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM working_state WHERE id = %s", (state_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def set_working_state(
    state_id: str = "default",
    active_threads: List[str] = None,
    open_questions: List[str] = None,
    partial_results: Dict = None,
    resume_hint: str = None,
    momentum: str = None
):
    """Save working state for session continuity"""
    now = datetime.now()
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO working_state
            (id, active_threads, open_questions, partial_results, resume_hint, momentum, updated_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                active_threads = COALESCE(%s, working_state.active_threads),
                open_questions = COALESCE(%s, working_state.open_questions),
                partial_results = COALESCE(%s, working_state.partial_results),
                resume_hint = COALESCE(%s, working_state.resume_hint),
                momentum = COALESCE(%s, working_state.momentum),
                updated_at = %s
        """, (
            state_id,
            json.dumps(active_threads or []),
            json.dumps(open_questions or []),
            json.dumps(partial_results or {}),
            resume_hint or "",
            momentum or "cold",
            now, now,
            json.dumps(active_threads) if active_threads is not None else None,
            json.dumps(open_questions) if open_questions is not None else None,
            json.dumps(partial_results) if partial_results is not None else None,
            resume_hint,
            momentum,
            now
        ))


def clear_working_state(state_id: str = "default"):
    """Clear working state"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM working_state WHERE id = %s", (state_id,))


# ============ Migration Functions ============

def migrate_from_sqlite(sqlite_path: str) -> Dict[str, int]:
    """
    Migrate data from SQLite to PostgreSQL.

    Returns dict with counts of migrated records per table.
    """
    import sqlite3

    if not os.path.exists(sqlite_path):
        log_with_context(logger, "warning", "SQLite database not found", path=sqlite_path)
        return {"error": "SQLite database not found"}

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    migrated = {}

    try:
        # Migrate ingest_log
        cursor = sqlite_conn.execute("SELECT * FROM ingest_log")
        rows = cursor.fetchall()
        migrated["ingest_log"] = 0

        for row in rows:
            try:
                record_ingest(
                    source_path=row["source_path"],
                    namespace=row["namespace"],
                    ingest_type=row["ingest_type"],
                    ingest_ts=row["ingest_ts"],
                    chunks_upserted=row["chunks_upserted"] or 0,
                    status=row["status"],
                    error_msg=row["error_msg"]
                )
                migrated["ingest_log"] += 1
            except Exception as e:
                log_with_context(logger, "warning", "Failed to migrate ingest record",
                               source=row["source_path"], error=str(e))

        # Migrate conversations
        cursor = sqlite_conn.execute("SELECT * FROM conversations")
        rows = cursor.fetchall()
        migrated["conversations"] = 0

        for row in rows:
            try:
                create_session(row["session_id"], row["namespace"])
                migrated["conversations"] += 1
            except Exception as e:
                log_with_context(logger, "debug", "Conversation already exists or error",
                               session=row["session_id"], error=str(e))

        # Migrate telegram_users
        cursor = sqlite_conn.execute("SELECT * FROM telegram_users")
        rows = cursor.fetchall()
        migrated["telegram_users"] = 0

        for row in rows:
            try:
                set_telegram_user_state(
                    user_id=row["user_id"],
                    session_id=row["session_id"],
                    namespace=row["namespace"],
                    role=row["role"]
                )
                migrated["telegram_users"] += 1
            except Exception as e:
                log_with_context(logger, "debug", "Telegram user migration error",
                               user_id=row["user_id"], error=str(e))

        log_with_context(logger, "info", "SQLite migration completed", migrated=migrated)

    finally:
        sqlite_conn.close()

    return migrated


def migrate_connector_json(state_dir: str) -> Dict[str, int]:
    """
    Migrate connector state from JSON files to PostgreSQL.

    Returns dict with counts of migrated connectors.
    """
    from pathlib import Path

    state_path = Path(state_dir)
    if not state_path.exists():
        log_with_context(logger, "warning", "Connector state directory not found", path=state_dir)
        return {"error": "Directory not found"}

    migrated = {"connectors": 0}

    for json_file in state_path.glob("*.json"):
        if json_file.name.startswith("."):
            continue

        try:
            with open(json_file, "r") as f:
                data = json.load(f)

            upsert_connector_state(
                connector_id=data.get("connector_id", json_file.stem),
                connector_type=data.get("connector_type", "unknown"),
                namespace=data.get("namespace", "private"),
                last_sync_cursor=data.get("last_sync_cursor"),
                last_sync_ts=data.get("last_sync_ts"),
                enabled=data.get("enabled", True),
                consecutive_errors=data.get("consecutive_errors", 0),
                last_error=data.get("last_error"),
                total_items_synced=data.get("total_items_synced", 0),
                total_errors=data.get("total_errors", 0),
                config=data.get("config", {}),
                sync_history=data.get("sync_history", [])
            )
            migrated["connectors"] += 1

        except Exception as e:
            log_with_context(logger, "warning", "Failed to migrate connector",
                           file=str(json_file), error=str(e))

    log_with_context(logger, "info", "Connector migration completed", migrated=migrated)
    return migrated


# ============ Active Context Buffer Functions (ADHD Optimization) ============

MAX_BUFFER_SIZE = 5  # ADHD optimization: limit cognitive load


def get_active_buffer(state_id: str = "default") -> List[Dict]:
    """
    Get the current active context buffer.
    Returns threads ordered by priority (highest first), then last_touched.
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM active_context_buffer
            WHERE state_id = %s AND status = 'active'
            ORDER BY priority DESC, last_touched_at DESC
        """, (state_id,))
        return [dict(row) for row in cur.fetchall()]


def get_buffer_thread(thread_id: str) -> Optional[Dict]:
    """Get a specific thread by ID"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM active_context_buffer WHERE id = %s", (thread_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def add_context_thread(
    thread_id: str,
    title: str,
    state_id: str = "default",
    context_summary: str = None,
    priority: int = 3,
    thread_type: str = "task",
    metadata: Dict = None
) -> Dict:
    """
    Add a thread to the active context buffer.

    If buffer is full (5 threads), automatically evicts the lowest priority thread.

    Args:
        thread_id: Unique identifier for the thread
        title: Short title describing the thread
        state_id: Working state ID (default: 'default')
        context_summary: Brief context/notes for resumption
        priority: 1-5 (5 = highest priority)
        thread_type: 'task', 'conversation', 'research', 'waiting'
        metadata: Additional JSON metadata

    Returns:
        Dict with thread info and any eviction that occurred
    """
    now = datetime.now()
    evicted = None

    # Check current buffer size
    current_buffer = get_active_buffer(state_id)

    # Check if thread already exists
    existing = get_buffer_thread(thread_id)
    if existing and existing.get("status") == "active":
        # Update existing thread
        return touch_context_thread(thread_id, context_summary=context_summary, priority=priority)

    # Evict if at capacity
    if len(current_buffer) >= MAX_BUFFER_SIZE:
        evicted = _evict_lowest_priority(state_id, f"Making room for: {title}")

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO active_context_buffer
            (id, state_id, title, context_summary, priority, status, thread_type, metadata, added_at, last_touched_at)
            VALUES (%s, %s, %s, %s, %s, 'active', %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = 'active',
                title = EXCLUDED.title,
                context_summary = EXCLUDED.context_summary,
                priority = EXCLUDED.priority,
                thread_type = EXCLUDED.thread_type,
                metadata = EXCLUDED.metadata,
                last_touched_at = EXCLUDED.last_touched_at,
                evicted_reason = NULL
        """, (
            thread_id, state_id, title, context_summary, priority,
            thread_type, json.dumps(metadata or {}), now, now
        ))

    log_with_context(logger, "info", "Context thread added",
                    thread_id=thread_id, title=title, priority=priority)

    return {
        "thread_id": thread_id,
        "title": title,
        "priority": priority,
        "status": "added",
        "evicted": evicted,
        "buffer_size": min(len(current_buffer) + 1, MAX_BUFFER_SIZE)
    }


def _evict_lowest_priority(state_id: str, reason: str = None) -> Optional[Dict]:
    """
    Evict the lowest priority (and oldest touched) thread from the buffer.
    Returns info about the evicted thread.
    """
    now = datetime.now()

    with get_cursor() as cur:
        # Find lowest priority, oldest touched thread
        cur.execute("""
            SELECT id, title, priority, context_summary
            FROM active_context_buffer
            WHERE state_id = %s AND status = 'active'
            ORDER BY priority ASC, last_touched_at ASC
            LIMIT 1
        """, (state_id,))

        victim = cur.fetchone()
        if not victim:
            return None

        # Mark as evicted
        cur.execute("""
            UPDATE active_context_buffer
            SET status = 'evicted', evicted_reason = %s, last_touched_at = %s
            WHERE id = %s
        """, (reason, now, victim["id"]))

        log_with_context(logger, "info", "Context thread evicted",
                        thread_id=victim["id"], reason=reason)

        return {
            "thread_id": victim["id"],
            "title": victim["title"],
            "priority": victim["priority"],
            "context_summary": victim["context_summary"],
            "reason": reason
        }


def touch_context_thread(
    thread_id: str,
    context_summary: str = None,
    priority: int = None
) -> Optional[Dict]:
    """
    Update a thread's last_touched timestamp and optionally update context/priority.
    Call this when switching focus to a thread.
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("SELECT * FROM active_context_buffer WHERE id = %s", (thread_id,))
        thread = cur.fetchone()

        if not thread:
            return None

        updates = ["last_touched_at = %s"]
        params = [now]

        if context_summary is not None:
            updates.append("context_summary = %s")
            params.append(context_summary)

        if priority is not None:
            updates.append("priority = %s")
            params.append(priority)

        params.append(thread_id)

        cur.execute(f"""
            UPDATE active_context_buffer
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """, params)

        result = cur.fetchone()
        return dict(result) if result else None


def complete_context_thread(thread_id: str, completion_note: str = None) -> Optional[Dict]:
    """
    Mark a thread as completed and remove from active buffer.
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            UPDATE active_context_buffer
            SET status = 'completed', completed_at = %s, last_touched_at = %s,
                context_summary = COALESCE(%s, context_summary)
            WHERE id = %s
            RETURNING *
        """, (now, now, completion_note, thread_id))

        result = cur.fetchone()
        if result:
            log_with_context(logger, "info", "Context thread completed", thread_id=thread_id)
            return dict(result)
        return None


def pause_context_thread(thread_id: str, reason: str = None) -> Optional[Dict]:
    """
    Pause a thread (remove from active buffer but preserve context).
    Use for threads that are blocked or intentionally deferred.
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            UPDATE active_context_buffer
            SET status = 'paused', last_touched_at = %s,
                evicted_reason = %s
            WHERE id = %s
            RETURNING *
        """, (now, reason, thread_id))

        result = cur.fetchone()
        if result:
            log_with_context(logger, "info", "Context thread paused",
                           thread_id=thread_id, reason=reason)
            return dict(result)
        return None


def resume_context_thread(thread_id: str, priority: int = None) -> Dict:
    """
    Resume a paused or evicted thread back to active status.
    May evict another thread if buffer is full.
    """
    thread = get_buffer_thread(thread_id)
    if not thread:
        return {"error": "Thread not found", "thread_id": thread_id}

    return add_context_thread(
        thread_id=thread_id,
        title=thread["title"],
        state_id=thread["state_id"],
        context_summary=thread["context_summary"],
        priority=priority or thread["priority"],
        thread_type=thread["thread_type"],
        metadata=thread.get("metadata")
    )


def get_buffer_stats(state_id: str = "default") -> Dict:
    """
    Get statistics about the context buffer.
    """
    with get_cursor() as cur:
        # Active threads
        cur.execute("""
            SELECT COUNT(*) as active_count,
                   AVG(priority) as avg_priority
            FROM active_context_buffer
            WHERE state_id = %s AND status = 'active'
        """, (state_id,))
        active = cur.fetchone()

        # By status
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM active_context_buffer
            WHERE state_id = %s
            GROUP BY status
        """, (state_id,))
        by_status = {row["status"]: row["count"] for row in cur.fetchall()}

        # Recently evicted (for recovery)
        cur.execute("""
            SELECT id, title, priority, evicted_reason, last_touched_at
            FROM active_context_buffer
            WHERE state_id = %s AND status = 'evicted'
            ORDER BY last_touched_at DESC
            LIMIT 5
        """, (state_id,))
        recently_evicted = [dict(row) for row in cur.fetchall()]

        # Paused threads (for resumption)
        cur.execute("""
            SELECT id, title, priority, context_summary, last_touched_at
            FROM active_context_buffer
            WHERE state_id = %s AND status = 'paused'
            ORDER BY priority DESC, last_touched_at DESC
        """, (state_id,))
        paused = [dict(row) for row in cur.fetchall()]

        return {
            "active_count": active["active_count"] or 0,
            "max_capacity": MAX_BUFFER_SIZE,
            "slots_available": MAX_BUFFER_SIZE - (active["active_count"] or 0),
            "avg_priority": round(float(active["avg_priority"] or 0), 1),
            "by_status": by_status,
            "recently_evicted": recently_evicted,
            "paused_threads": paused
        }


def get_focus_suggestion(state_id: str = "default") -> Dict:
    """
    Get a suggestion for what to focus on next.
    Returns the highest priority thread that was touched longest ago.
    """
    with get_cursor() as cur:
        # Get highest priority, least recently touched
        cur.execute("""
            SELECT id, title, priority, context_summary, thread_type,
                   last_touched_at,
                   EXTRACT(EPOCH FROM (NOW() - last_touched_at)) / 60 as minutes_since_touch
            FROM active_context_buffer
            WHERE state_id = %s AND status = 'active'
            ORDER BY priority DESC, last_touched_at ASC
            LIMIT 1
        """, (state_id,))

        suggestion = cur.fetchone()

        if not suggestion:
            return {
                "suggestion": None,
                "message": "No active threads. Time to add something to focus on!"
            }

        minutes = int(suggestion["minutes_since_touch"] or 0)

        return {
            "suggestion": dict(suggestion),
            "message": f"Focus on: {suggestion['title']} (priority {suggestion['priority']}, untouched for {minutes} min)",
            "thread_id": suggestion["id"]
        }


def clear_buffer(state_id: str = "default", keep_completed: bool = True) -> Dict:
    """
    Clear the active context buffer.

    Args:
        state_id: Which state's buffer to clear
        keep_completed: If True, only clears active/paused threads
    """
    with get_cursor() as cur:
        if keep_completed:
            cur.execute("""
                DELETE FROM active_context_buffer
                WHERE state_id = %s AND status IN ('active', 'paused', 'evicted')
            """, (state_id,))
        else:
            cur.execute("""
                DELETE FROM active_context_buffer WHERE state_id = %s
            """, (state_id,))

        deleted = cur.rowcount

    log_with_context(logger, "info", "Context buffer cleared",
                    state_id=state_id, deleted=deleted)

    return {"deleted": deleted, "state_id": state_id}


# ============ System Capability Update Functions ============

def add_capability_update(
    update_type: str,
    title: str,
    description: str,
    source: str = "claude_code",
    version: str = None,
    expires_hours: int = 168  # 7 days default
) -> int:
    """
    Add a system capability update notification.

    Used by Claude Code to notify Jarvis about new features/fixes.

    Args:
        update_type: One of 'capability', 'feature', 'fix', 'behavior'
        title: Short title (e.g., "File Upload via Telegram")
        description: Detailed description of the update
        source: Source of update (default: claude_code)
        version: Related prompt version (optional)
        expires_hours: Hours until this update expires (default: 7 days)

    Returns:
        ID of created update
    """
    from datetime import timedelta

    expires_at = datetime.now() + timedelta(hours=expires_hours) if expires_hours else None

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO system_capability_update
            (update_type, title, description, source, version, expires_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (update_type, title, description, source, version, expires_at))

        row = cur.fetchone()
        update_id = row["id"] if row else None

    log_with_context(logger, "info", "Capability update added",
                    update_id=update_id, update_type=update_type, title=title)

    return update_id


def get_recent_capability_updates(
    hours: int = 168,  # 7 days
    include_expired: bool = False,
    limit: int = 10
) -> List[Dict]:
    """
    Get recent capability updates for prompt injection.

    Args:
        hours: How far back to look
        include_expired: Include expired updates
        limit: Max number of updates

    Returns:
        List of update dicts
    """
    from datetime import timedelta

    since = datetime.now() - timedelta(hours=hours)

    with get_cursor() as cur:
        if include_expired:
            cur.execute("""
                SELECT * FROM system_capability_update
                WHERE created_at >= %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (since, limit))
        else:
            cur.execute("""
                SELECT * FROM system_capability_update
                WHERE created_at >= %s
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY created_at DESC
                LIMIT %s
            """, (since, limit))

        return [dict(row) for row in cur.fetchall()]


def get_capability_updates_for_prompt() -> str:
    """
    Get formatted capability updates for prompt injection.

    Returns a string suitable for appending to the system prompt.
    """
    updates = get_recent_capability_updates(hours=168, limit=5)

    if not updates:
        return ""

    lines = ["\n## Aktuelle System-Updates"]
    for u in updates:
        update_type = u.get("update_type", "update")
        title = u.get("title", "Unknown")
        description = u.get("description", "")
        created = u.get("created_at")
        date_str = created.strftime("%d.%m.%Y") if created else "?"

        type_emoji = {
            "capability": "🆕",
            "feature": "✨",
            "fix": "🔧",
            "behavior": "📝"
        }.get(update_type, "📌")

        lines.append(f"- {type_emoji} **{title}** ({date_str}): {description}")

    return "\n".join(lines)


def clear_expired_capability_updates() -> int:
    """Remove expired capability updates."""
    with get_cursor() as cur:
        cur.execute("""
            DELETE FROM system_capability_update
            WHERE expires_at IS NOT NULL AND expires_at < NOW()
        """)
        deleted = cur.rowcount

    log_with_context(logger, "info", "Expired capability updates cleared", deleted=deleted)
    return deleted


# ============ Alert Deduplication Cache Functions ============

# TTL for alert cache entries (24 hours)
_ALERT_CACHE_TTL_HOURS = 24


def is_alert_sent(email_id: str) -> bool:
    """
    Check if an alert was already sent for this email (persisted in Postgres).

    Returns True if alert was sent within the last 24 hours.
    """
    if not email_id:
        return False

    with get_cursor() as cur:
        cur.execute("""
            SELECT 1 FROM alert_sent_cache
            WHERE email_id = %s
              AND sent_at > NOW() - INTERVAL '%s hours'
        """, (email_id, _ALERT_CACHE_TTL_HOURS))
        return cur.fetchone() is not None


def mark_alert_sent(email_id: str):
    """
    Mark an email as having triggered an alert (persisted in Postgres).
    """
    if not email_id:
        return

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO alert_sent_cache (email_id, sent_at)
            VALUES (%s, NOW())
            ON CONFLICT (email_id) DO UPDATE SET sent_at = NOW()
        """, (email_id,))


def is_deadline_alert_sent(cache_key: str) -> bool:
    """
    Check if a deadline alert was already sent for this event+level combo.
    Uses the same alert_sent_cache table with a different key format.

    cache_key format: "deadline:{event_id}:{level}"
    """
    if not cache_key:
        return False

    with get_cursor() as cur:
        cur.execute("""
            SELECT 1 FROM alert_sent_cache
            WHERE email_id = %s AND sent_at > NOW() - INTERVAL '24 hours'
        """, (cache_key,))
        return cur.fetchone() is not None


def mark_deadline_alert_sent(cache_key: str):
    """
    Mark a deadline alert as sent for deduplication.

    cache_key format: "deadline:{event_id}:{level}"
    """
    if not cache_key:
        return

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO alert_sent_cache (email_id, sent_at)
            VALUES (%s, NOW())
            ON CONFLICT (email_id) DO UPDATE SET sent_at = NOW()
        """, (cache_key,))


def cleanup_alert_cache() -> int:
    """
    Remove old entries from alert cache (older than 24 hours).

    Returns number of deleted entries.
    """
    with get_cursor() as cur:
        cur.execute("""
            DELETE FROM alert_sent_cache
            WHERE sent_at < NOW() - INTERVAL '%s hours'
        """, (_ALERT_CACHE_TTL_HOURS,))
        deleted = cur.rowcount

    if deleted > 0:
        log_with_context(logger, "debug", "Alert cache cleaned up", deleted=deleted)
    return deleted


def clear_alert_cache() -> int:
    """Clear entire alert cache (for manual reset)."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM alert_sent_cache")
        deleted = cur.rowcount

    log_with_context(logger, "info", "Alert cache cleared", deleted=deleted)
    return deleted


def get_alert_cache_stats() -> Dict:
    """Get statistics about the alert cache."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM alert_sent_cache")
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT COUNT(*) as count FROM alert_sent_cache
            WHERE sent_at > NOW() - INTERVAL '1 hour'
        """)
        last_hour = cur.fetchone()["count"]

    return {
        "total_entries": total,
        "last_hour": last_hour,
        "ttl_hours": _ALERT_CACHE_TTL_HOURS
    }


# ============ Decision Outcome & Salience Functions (Phase 12.3) ============

def record_decision_outcome(
    decision_id: str,
    outcome_rating: int,
    knowledge_item_ids: List[str] = None,
    outcome_notes: str = None,
    decision_context: str = None,
    decision_type: str = "general",
    user_id: int = None
) -> Dict:
    """
    Record the outcome of a decision that used knowledge items.

    Args:
        decision_id: Unique identifier for the decision
        outcome_rating: 1-10 rating (1=very negative, 10=very positive)
        knowledge_item_ids: List of knowledge item IDs that contributed
        outcome_notes: Optional notes about the outcome
        decision_context: Context of the decision (what was decided)
        decision_type: Type of decision (meeting, email, task, etc.)
        user_id: User who made the decision

    Returns:
        Dict with created/updated decision outcome
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO decision_outcome
            (decision_id, knowledge_item_ids, outcome_rating, outcome_notes,
             decision_context, decision_type, user_id, recorded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (decision_id) DO UPDATE SET
                outcome_rating = EXCLUDED.outcome_rating,
                outcome_notes = EXCLUDED.outcome_notes,
                knowledge_item_ids = EXCLUDED.knowledge_item_ids,
                recorded_at = EXCLUDED.recorded_at
            RETURNING id
        """, (
            decision_id,
            json.dumps(knowledge_item_ids or []),
            outcome_rating,
            outcome_notes,
            decision_context,
            decision_type,
            user_id,
            now
        ))

        result = cur.fetchone()

    # Update salience for each knowledge item
    if knowledge_item_ids:
        _update_salience_from_outcome(knowledge_item_ids, outcome_rating, now)

    log_with_context(logger, "info", "Decision outcome recorded",
                    decision_id=decision_id, outcome_rating=outcome_rating,
                    knowledge_items=len(knowledge_item_ids or []))

    return {
        "id": result["id"] if result else None,
        "decision_id": decision_id,
        "outcome_rating": outcome_rating,
        "knowledge_items_updated": len(knowledge_item_ids or [])
    }


def _update_salience_from_outcome(
    knowledge_item_ids: List[str],
    outcome_rating: int,
    recorded_at: datetime
):
    """
    Update salience scores for knowledge items based on decision outcome.

    Positive outcomes (>= 7) boost decision_impact.
    Negative outcomes (<= 3) reduce decision_impact.
    """
    is_positive = outcome_rating >= 7
    is_negative = outcome_rating <= 3
    impact_delta = 0.1 if is_positive else (-0.05 if is_negative else 0.02)

    with get_cursor() as cur:
        for item_id in knowledge_item_ids:
            # Upsert salience record
            cur.execute("""
                INSERT INTO knowledge_salience
                (knowledge_item_id, decision_impact, positive_outcomes, negative_outcomes,
                 last_used_in_decision, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (knowledge_item_id) DO UPDATE SET
                    decision_impact = LEAST(1.0, GREATEST(0.0,
                        knowledge_salience.decision_impact + %s)),
                    positive_outcomes = knowledge_salience.positive_outcomes + %s,
                    negative_outcomes = knowledge_salience.negative_outcomes + %s,
                    last_used_in_decision = %s,
                    updated_at = %s
            """, (
                item_id,
                max(0.0, min(1.0, 0.5 + impact_delta)),  # Initial value
                1 if is_positive else 0,
                1 if is_negative else 0,
                recorded_at,
                recorded_at,
                impact_delta,
                1 if is_positive else 0,
                1 if is_negative else 0,
                recorded_at,
                recorded_at
            ))

            # Recalculate salience score
            _recalculate_salience(cur, item_id)


def _recalculate_salience(cur, knowledge_item_id: str):
    """
    Recalculate the overall salience score for a knowledge item.

    Formula aligned with knowledge_db.py (Phase 15.5):
    - 35% decision_impact (outcome-based learning, persists)
    - 30% goal_relevance (alignment with current goals, decays)
    - 20% surprise_factor (novelty/unexpectedness, decays fast)
    - 15% baseline (fixed at 0.5, since relevance_score not in this table)

    Total: 0.35*d + 0.30*g + 0.20*s + 0.075 (baseline contribution)
    """
    cur.execute("""
        UPDATE knowledge_salience
        SET salience_score = (
            0.35 * decision_impact +
            0.30 * goal_relevance +
            0.20 * surprise_factor +
            0.075
        ),
        updated_at = NOW()
        WHERE knowledge_item_id = %s
    """, (knowledge_item_id,))


def get_knowledge_salience(knowledge_item_id: str) -> Optional[Dict]:
    """Get salience data for a specific knowledge item."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM knowledge_salience
            WHERE knowledge_item_id = %s
        """, (knowledge_item_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_salience_scores(knowledge_item_ids: List[str]) -> Dict[str, float]:
    """
    Get salience scores for multiple knowledge items.
    Returns dict mapping item_id -> salience_score.
    """
    if not knowledge_item_ids:
        return {}

    with get_cursor() as cur:
        placeholders = ",".join(["%s"] * len(knowledge_item_ids))
        cur.execute(f"""
            SELECT knowledge_item_id, salience_score
            FROM knowledge_salience
            WHERE knowledge_item_id IN ({placeholders})
        """, knowledge_item_ids)

        return {row["knowledge_item_id"]: float(row["salience_score"] or 0.0)
                for row in cur.fetchall()}


def get_salience_scores_by_source(source_paths: List[str]) -> Dict[str, float]:
    """
    Get salience scores for knowledge items by their source_path.

    This is the preferred method for hybrid_search since Qdrant results
    contain source_path but not knowledge_item integer IDs.

    Added in Phase 18: Data Pipeline Consistency Fixes.

    Returns dict mapping source_path -> salience_score.
    """
    if not source_paths:
        return {}

    try:
        # Import here to avoid circular imports
        from .knowledge_db import get_conn

        with get_conn() as conn:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(source_paths))

            # Join knowledge_item with knowledge_salience via id
            # knowledge_salience.knowledge_item_id stores the knowledge_item.id as TEXT
            cur.execute(f"""
                SELECT ki.source_path, ks.salience_score
                FROM knowledge_item ki
                JOIN knowledge_salience ks ON ki.id::text = ks.knowledge_item_id
                WHERE ki.source_path IN ({placeholders})
                AND ki.status = 'active'
            """, source_paths)

            return {row["source_path"]: float(row["salience_score"] or 0.0)
                    for row in cur.fetchall()}

    except Exception as e:
        log_with_context(logger, "debug", "Could not fetch salience by source_path",
                        error=str(e), count=len(source_paths))
        return {}


def update_goal_relevance(
    knowledge_item_id: str,
    goal_relevance: float,
    goal_id: str = None
) -> bool:
    """
    Update goal relevance for a knowledge item.

    Called when knowledge is linked to an active goal.
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO knowledge_salience
            (knowledge_item_id, goal_relevance, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (knowledge_item_id) DO UPDATE SET
                goal_relevance = GREATEST(knowledge_salience.goal_relevance, %s),
                updated_at = %s
        """, (knowledge_item_id, goal_relevance, now, goal_relevance, now))

        _recalculate_salience(cur, knowledge_item_id)

    return True


def update_surprise_factor(
    knowledge_item_id: str,
    surprise_factor: float
) -> bool:
    """
    Update surprise factor for a knowledge item.

    Higher surprise = more novel/unexpected information.
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO knowledge_salience
            (knowledge_item_id, surprise_factor, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (knowledge_item_id) DO UPDATE SET
                surprise_factor = %s,
                updated_at = %s
        """, (knowledge_item_id, surprise_factor, now, surprise_factor, now))

        _recalculate_salience(cur, knowledge_item_id)

    return True


def get_high_salience_items(limit: int = 20, min_salience: float = 0.3) -> List[Dict]:
    """
    Get knowledge items with high salience scores.

    Useful for prioritizing what to show in context.
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT *
            FROM knowledge_salience
            WHERE salience_score >= %s
            ORDER BY salience_score DESC
            LIMIT %s
        """, (min_salience, limit))

        return [dict(row) for row in cur.fetchall()]


def get_salience_stats() -> Dict:
    """Get statistics about salience data."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total_items,
                AVG(salience_score) as avg_salience,
                AVG(decision_impact) as avg_decision_impact,
                AVG(goal_relevance) as avg_goal_relevance,
                SUM(positive_outcomes) as total_positive,
                SUM(negative_outcomes) as total_negative
            FROM knowledge_salience
        """)
        row = cur.fetchone()

        cur.execute("SELECT COUNT(*) as count FROM decision_outcome")
        outcome_count = cur.fetchone()["count"]

    return {
        "total_items_with_salience": row["total_items"] or 0,
        "avg_salience": round(float(row["avg_salience"] or 0), 3),
        "avg_decision_impact": round(float(row["avg_decision_impact"] or 0), 3),
        "avg_goal_relevance": round(float(row["avg_goal_relevance"] or 0), 3),
        "total_positive_outcomes": row["total_positive"] or 0,
        "total_negative_outcomes": row["total_negative"] or 0,
        "total_decisions_recorded": outcome_count
    }


# ============ Profile Staging Functions (Phase 15) ============

def stage_profile(
    profile_data: Dict,
    source: str = "manual_upload",
    target_person_id: str = None,
    confidence_score: float = 0.5
) -> Dict:
    """
    Stage a profile for approval before merging into knowledge.

    Args:
        profile_data: The profile JSON data (PersonProfileContent schema)
        source: Where the profile came from (manual_upload, whatsapp_analysis,
                email_analysis, google_chat_analysis)
        target_person_id: Optional - ID of existing person to update
        confidence_score: Initial confidence (0.0-1.0)

    Returns:
        Dict with staged profile info including ID
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO profile_staging
            (profile_data, source, target_person_id, confidence_score,
             status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s)
            RETURNING id
        """, (
            json.dumps(profile_data),
            source,
            target_person_id,
            confidence_score,
            now, now
        ))

        result = cur.fetchone()
        profile_id = result["id"] if result else None

    log_with_context(logger, "info", "Profile staged for approval",
                    profile_id=profile_id, source=source,
                    target=target_person_id)

    return {
        "id": profile_id,
        "status": "pending",
        "source": source,
        "target_person_id": target_person_id,
        "confidence_score": confidence_score,
        "created_at": str(now)
    }


def get_staged_profile(profile_id: int) -> Optional[Dict]:
    """Get a specific staged profile by ID."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM profile_staging WHERE id = %s
        """, (profile_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_pending_profiles(limit: int = 20) -> List[Dict]:
    """Get all profiles pending approval."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, profile_data, source, target_person_id,
                   confidence_score, created_at, comparison_results
            FROM profile_staging
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
        """, (limit,))
        return [dict(row) for row in cur.fetchall()]


def update_comparison_results(
    profile_id: int,
    comparison_results: Dict
) -> bool:
    """
    Update comparison results for a staged profile.

    Called after analyzing WhatsApp/Email/Chat data and comparing
    with the staged profile.
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            UPDATE profile_staging
            SET comparison_results = %s, updated_at = %s
            WHERE id = %s
            RETURNING id
        """, (json.dumps(comparison_results), now, profile_id))

        return cur.fetchone() is not None


def approve_profile(
    profile_id: int,
    reviewed_by: str = "system",
    approval_notes: str = None,
    final_confidence: float = None
) -> Dict:
    """
    Approve a staged profile for merging.

    Args:
        profile_id: ID of the staged profile
        reviewed_by: Who approved (user ID or 'system')
        approval_notes: Optional notes about the approval
        final_confidence: Optional override for confidence score

    Returns:
        Dict with approval result
    """
    now = datetime.now()

    with get_cursor() as cur:
        updates = [
            "status = 'approved'",
            "reviewed_at = %s",
            "reviewed_by = %s",
            "updated_at = %s"
        ]
        params = [now, reviewed_by, now]

        if approval_notes:
            updates.append("approval_notes = %s")
            params.append(approval_notes)

        if final_confidence is not None:
            updates.append("confidence_score = %s")
            params.append(final_confidence)

        params.append(profile_id)

        cur.execute(f"""
            UPDATE profile_staging
            SET {', '.join(updates)}
            WHERE id = %s AND status = 'pending'
            RETURNING id, profile_data, target_person_id
        """, params)

        result = cur.fetchone()

        if not result:
            return {"error": "Profile not found or not pending", "profile_id": profile_id}

    log_with_context(logger, "info", "Profile approved",
                    profile_id=profile_id, reviewed_by=reviewed_by)

    return {
        "id": result["id"],
        "status": "approved",
        "profile_data": result["profile_data"],
        "target_person_id": result["target_person_id"],
        "reviewed_at": str(now),
        "reviewed_by": reviewed_by
    }


def reject_profile(
    profile_id: int,
    reviewed_by: str = "system",
    rejection_reason: str = None
) -> Dict:
    """
    Reject a staged profile.

    Args:
        profile_id: ID of the staged profile
        reviewed_by: Who rejected
        rejection_reason: Why it was rejected

    Returns:
        Dict with rejection result
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            UPDATE profile_staging
            SET status = 'rejected',
                reviewed_at = %s,
                reviewed_by = %s,
                approval_notes = %s,
                updated_at = %s
            WHERE id = %s AND status = 'pending'
            RETURNING id
        """, (now, reviewed_by, rejection_reason, now, profile_id))

        result = cur.fetchone()

        if not result:
            return {"error": "Profile not found or not pending", "profile_id": profile_id}

    log_with_context(logger, "info", "Profile rejected",
                    profile_id=profile_id, reason=rejection_reason)

    return {
        "id": profile_id,
        "status": "rejected",
        "rejection_reason": rejection_reason,
        "reviewed_at": str(now),
        "reviewed_by": reviewed_by
    }


def mark_profile_merged(profile_id: int, knowledge_item_id: str) -> bool:
    """
    Mark a profile as merged after it's been added to knowledge.

    Args:
        profile_id: ID of the staged profile
        knowledge_item_id: ID of the created knowledge item
    """
    now = datetime.now()

    with get_cursor() as cur:
        cur.execute("""
            UPDATE profile_staging
            SET status = 'merged',
                updated_at = %s,
                comparison_results = comparison_results || %s
            WHERE id = %s AND status = 'approved'
            RETURNING id
        """, (now, json.dumps({"merged_to": knowledge_item_id}), profile_id))

        result = cur.fetchone()

        if result:
            log_with_context(logger, "info", "Profile merged to knowledge",
                           profile_id=profile_id, knowledge_item_id=knowledge_item_id)

        return result is not None


def get_profile_staging_stats() -> Dict:
    """Get statistics about profile staging."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM profile_staging
            GROUP BY status
        """)
        by_status = {row["status"]: row["count"] for row in cur.fetchall()}

        cur.execute("""
            SELECT source, COUNT(*) as count
            FROM profile_staging
            GROUP BY source
        """)
        by_source = {row["source"]: row["count"] for row in cur.fetchall()}

        cur.execute("""
            SELECT COUNT(*) as count
            FROM profile_staging
            WHERE status = 'pending' AND created_at < NOW() - INTERVAL '7 days'
        """)
        stale_pending = cur.fetchone()["count"]

    return {
        "by_status": by_status,
        "by_source": by_source,
        "total": sum(by_status.values()) if by_status else 0,
        "pending": by_status.get("pending", 0),
        "stale_pending": stale_pending
    }


def cleanup_old_staging(days: int = 90) -> int:
    """
    Remove old merged/rejected profiles from staging.

    Args:
        days: Remove profiles older than this many days

    Returns:
        Number of deleted profiles
    """
    with get_cursor() as cur:
        cur.execute("""
            DELETE FROM profile_staging
            WHERE status IN ('merged', 'rejected')
              AND updated_at < NOW() - INTERVAL '%s days'
        """, (days,))
        deleted = cur.rowcount

    if deleted > 0:
        log_with_context(logger, "info", "Old staged profiles cleaned up", deleted=deleted)

    return deleted


# ============ Phase 18: Cross-AI Learning Functions ============

def save_session_learning(
    session_id: str,
    source: str,
    summary: str = None,
    files_modified: List[str] = None,
    learnings: List[Dict] = None,
    code_changes: Dict = None,
    duration_minutes: int = None
) -> Dict:
    """
    Save an AI session learning record.

    Args:
        session_id: Unique session identifier
        source: claude_code, copilot, cursor, other
        summary: Text summary of the session
        files_modified: List of modified file paths
        learnings: List of {fact, category, confidence} dicts
        code_changes: {added_lines, removed_lines, files}
        duration_minutes: Session duration

    Returns:
        Dict with session info and created status
    """
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO ai_session_learnings
            (session_id, source, summary, files_modified, learnings,
             code_changes, duration_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                files_modified = EXCLUDED.files_modified,
                learnings = EXCLUDED.learnings,
                code_changes = EXCLUDED.code_changes,
                duration_minutes = EXCLUDED.duration_minutes
            RETURNING id, session_id, created_at
        """, (
            session_id,
            source,
            summary,
            json.dumps(files_modified or []),
            json.dumps(learnings or []),
            json.dumps(code_changes or {}),
            duration_minutes
        ))
        row = cur.fetchone()

    log_with_context(logger, "info", "Session learning saved",
                    session_id=session_id, source=source,
                    learnings_count=len(learnings or []))

    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "learnings_count": len(learnings or [])
    }


def get_session_learning(session_id: str) -> Optional[Dict]:
    """Get a specific session learning record."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM ai_session_learnings WHERE session_id = %s
        """, (session_id,))
        row = cur.fetchone()

        if row:
            result = dict(row)
            # Parse JSON fields
            result["files_modified"] = result.get("files_modified") or []
            result["learnings"] = result.get("learnings") or []
            result["code_changes"] = result.get("code_changes") or {}
            return result
        return None


def list_session_learnings(
    source: str = None,
    processed: bool = None,
    limit: int = 50
) -> List[Dict]:
    """
    List session learning records with optional filters.

    Args:
        source: Filter by source (claude_code, copilot, etc.)
        processed: Filter by processed status
        limit: Max results
    """
    with get_cursor() as cur:
        conditions = []
        params = []

        if source:
            conditions.append("source = %s")
            params.append(source)
        if processed is not None:
            conditions.append("processed = %s")
            params.append(processed)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        cur.execute(f"""
            SELECT id, session_id, source, summary,
                   jsonb_array_length(COALESCE(learnings, '[]'::jsonb)) as learnings_count,
                   jsonb_array_length(COALESCE(files_modified, '[]'::jsonb)) as files_count,
                   duration_minutes, processed, facts_extracted,
                   created_at, processed_at
            FROM ai_session_learnings
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, params)

        return [dict(row) for row in cur.fetchall()]


def mark_session_processed(session_id: str, facts_extracted: int = 0) -> bool:
    """Mark a session as processed after fact extraction."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE ai_session_learnings
            SET processed = TRUE,
                facts_extracted = %s,
                processed_at = NOW()
            WHERE session_id = %s
            RETURNING id
        """, (facts_extracted, session_id))
        return cur.fetchone() is not None


def get_migration_candidates(limit: int = 10) -> List[Dict]:
    """
    Get facts that are candidates for migration to permanent code.

    Uses memory_store.get_mature_facts() to get high-trust facts from SQLite,
    then calculates priority scores.

    Categories:
    - critical: priority >= 0.8
    - high: priority >= 0.6
    - medium: priority >= 0.4
    """
    from . import memory_store
    from datetime import datetime

    # Get mature facts from SQLite memory store
    try:
        mature_facts = memory_store.get_mature_facts(
            min_trust_score=0.5,
            min_access_count=3,
            min_age_days=3,
            exclude_migrated=True
        )
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get mature facts", error=str(e))
        return []

    candidates = []
    for fact in mature_facts[:limit * 2]:  # Get more than needed for filtering
        # Calculate priority score using ROADMAP formula
        trust = fact.get("trust_score", 0.5)
        access = fact.get("access_count", 0)
        # No salience in SQLite, default to 0.5
        salience = 0.5

        # Calculate age in weeks
        try:
            created = datetime.fromisoformat(fact.get("created_at", datetime.now().isoformat()))
            age_weeks = (datetime.now() - created).days / 7
        except Exception as e:
            log_with_context(logger, "debug", "Failed to parse fact timestamp", error=str(e))
            age_weeks = 1

        # Priority formula: trust*0.4 + (access/10)*0.3 + salience*0.2 + age_weeks*0.1
        priority_score = (
            trust * 0.4 +
            min(access / 10.0, 1.0) * 0.3 +
            salience * 0.2 +
            min(age_weeks, 4) * 0.025
        )

        # Determine category
        if priority_score >= 0.8:
            category = "critical"
        elif priority_score >= 0.6:
            category = "high"
        else:
            category = "medium"

        # Only include if meets minimum threshold
        if priority_score >= 0.4:
            candidates.append({
                "id": fact.get("id"),
                "fact_type": fact.get("category", "general"),
                "content": fact.get("fact", ""),
                "namespace": fact.get("source", ""),
                "trust_score": trust,
                "access_count": access,
                "salience": salience,
                "source": fact.get("source"),
                "created_at": fact.get("created_at"),
                "priority_score": round(priority_score, 3),
                "priority_category": category,
                "suggested_target": _suggest_migration_target(
                    fact.get("category"),
                    fact.get("source")
                )
            })

    # Sort by priority and limit
    candidates.sort(key=lambda x: x["priority_score"], reverse=True)
    return candidates[:limit]


def _suggest_migration_target(fact_type: str, namespace: str) -> str:
    """Suggest where a fact should be migrated to."""
    if not fact_type:
        return "policies/JARVIS_CONTEXT.md"

    type_lower = fact_type.lower()
    ns_lower = (namespace or "").lower()

    if "capability" in type_lower or "can_" in type_lower:
        return "policies/JARVIS_SELF.md"
    elif "preference" in type_lower or "style" in type_lower:
        return "policies/JARVIS_CONTEXT.md"
    elif "person" in type_lower or "contact" in ns_lower:
        return "knowledge/persons/{person_id}.yaml"
    elif "project" in type_lower or "project" in ns_lower:
        return "knowledge/projects/{project_id}.yaml"
    elif "config" in type_lower:
        return "config/jarvis_config.yaml"
    else:
        return "policies/JARVIS_CONTEXT.md"


def get_session_learning_stats() -> Dict:
    """Get statistics about session learnings."""
    with get_cursor() as cur:
        # Total counts by source
        cur.execute("""
            SELECT source, COUNT(*) as count,
                   SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed,
                   SUM(facts_extracted) as facts_total,
                   AVG(duration_minutes) as avg_duration
            FROM ai_session_learnings
            GROUP BY source
        """)
        by_source = {
            row["source"]: {
                "sessions": row["count"],
                "processed": row["processed"],
                "facts_extracted": row["facts_total"] or 0,
                "avg_duration_mins": round(row["avg_duration"] or 0, 1)
            }
            for row in cur.fetchall()
        }

        # Recent activity
        cur.execute("""
            SELECT COUNT(*) as count
            FROM ai_session_learnings
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        recent = cur.fetchone()["count"]

        # Unprocessed count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM ai_session_learnings
            WHERE processed = FALSE
        """)
        unprocessed = cur.fetchone()["count"]

    return {
        "by_source": by_source,
        "total_sessions": sum(s["sessions"] for s in by_source.values()) if by_source else 0,
        "total_facts_extracted": sum(s["facts_extracted"] for s in by_source.values()) if by_source else 0,
        "sessions_last_7_days": recent,
        "unprocessed_sessions": unprocessed
    }


# Initialize schema on import
try:
    init_state_schema()
except Exception as e:
    log_with_context(logger, "warning", "Could not initialize state schema", error=str(e))
