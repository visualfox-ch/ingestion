"""
Jarvis Knowledge Layer
PostgreSQL-based mutable knowledge with versioning and HITL review.

Separates immutable evidence (Qdrant) from mutable knowledge (profiles, personas, insights).
All changes are versioned and can go through human review.
"""
import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from contextlib import contextmanager

from .observability import get_logger, log_with_context
from .db_safety import safe_list_query, safe_write_query, safe_aggregate_query
from .connection_pool_metrics import get_pool_metrics
from . import postgres_state

logger = get_logger("jarvis.knowledge")

def _get_pool():
    """Return shared ThreadedConnectionPool from postgres_state."""
    return postgres_state.get_pool()


def get_pool_stats() -> Dict[str, Any]:
    """Get current connection pool statistics."""
    pool = _get_pool()
    if pool is None:
        return {"error": "Pool not initialized"}

    used = len(getattr(pool, "_used", {}) or {})
    available = len(getattr(pool, "_pool", []) or [])
    total = used + available
    
    metrics = get_pool_metrics("knowledge_db")
    metrics.record_pool_state(total=total, in_use=used, available=available)
    return {
        "pool_name": "knowledge_db",
        "minconn": int(os.environ.get("DB_POOL_MIN", "5")),
        "maxconn": int(os.environ.get("DB_POOL_MAX", "75")),
        "pool_size_total": total,
        "pool_in_use": used,
        "pool_available": available,
        "total_acquired": metrics.total_acquired,
        "total_released": metrics.total_released,
        "avg_wait_ms": round(metrics.get_avg_wait_time() * 1000, 2),
        "p95_wait_ms": round(metrics.get_p95_wait_time() * 1000, 2),
        "p99_wait_ms": round(metrics.get_p99_wait_time() * 1000, 2),
        "max_wait_ms": round(metrics.max_wait_time * 1000, 2),
    }


@contextmanager
def get_conn():
    """Get connection from pool with automatic return and metrics tracking."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    pool = _get_pool()
    metrics = get_pool_metrics("knowledge_db")
    
    # Track acquisition time
    start_time = time.time()
    conn = pool.getconn()
    wait_time = time.time() - start_time
    metrics.record_acquisition(wait_time)
    try:
        used = len(getattr(pool, "_used", {}) or {})
        available = len(getattr(pool, "_pool", []) or [])
        metrics.record_pool_state(total=used + available, in_use=used, available=available)
    except Exception:
        pass
    
    if wait_time > 0.1:  # Log if waiting >100ms
        log_with_context(logger, "warning", "Slow pool acquisition", 
                       wait_time_ms=int(wait_time * 1000))
    
    conn.cursor_factory = RealDictCursor
    try:
        with conn.cursor() as cur:
            timeout_ms = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))
            cur.execute(f"SET statement_timeout = {timeout_ms}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
        metrics.record_release()
        try:
            used = len(getattr(pool, "_used", {}) or {})
            available = len(getattr(pool, "_pool", []) or [])
            metrics.record_pool_state(total=used + available, in_use=used, available=available)
        except Exception:
            pass


def close_pool():
    """Close all connections in the pool (shutdown handler)"""
    postgres_state.close_pool()


def is_available() -> bool:
    """Check if knowledge DB is available"""
    try:
        with safe_list_query(timeout=5, table='knowledge') as cur:
            cur.execute("SELECT 1")
            return True
    except Exception:
        return False


# ============ Schema Initialization ============

DDL_STATEMENTS = """
-- Person Profiles (versioned)
CREATE TABLE IF NOT EXISTS person_profile (
    id SERIAL PRIMARY KEY,
    person_id VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    org VARCHAR(255),
    profile_type VARCHAR(50) DEFAULT 'internal',
    languages JSONB DEFAULT '["de"]',
    timezone VARCHAR(100) DEFAULT 'Europe/Zurich',
    status VARCHAR(50) DEFAULT 'draft',
    current_version_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_person_profile_person_id ON person_profile(person_id);
CREATE INDEX IF NOT EXISTS idx_person_profile_status ON person_profile(status);

CREATE TABLE IF NOT EXISTS person_profile_version (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,
    changed_by VARCHAR(100) NOT NULL,
    change_reason TEXT,
    change_type VARCHAR(50) NOT NULL,
    evidence_sources JSONB,
    status VARCHAR(50) DEFAULT 'proposed',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(profile_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_ppv_profile_id ON person_profile_version(profile_id);
CREATE INDEX IF NOT EXISTS idx_ppv_status ON person_profile_version(status);

-- Persona Styles (versioned)
CREATE TABLE IF NOT EXISTS persona_style (
    id SERIAL PRIMARY KEY,
    persona_id VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    status VARCHAR(50) DEFAULT 'active',
    current_version_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persona_style_persona_id ON persona_style(persona_id);

CREATE TABLE IF NOT EXISTS persona_style_version (
    id SERIAL PRIMARY KEY,
    persona_id INTEGER NOT NULL REFERENCES persona_style(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,
    changed_by VARCHAR(100) NOT NULL,
    change_reason TEXT,
    change_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'proposed',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(persona_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_psv_persona_id ON persona_style_version(persona_id);
CREATE INDEX IF NOT EXISTS idx_psv_status ON persona_style_version(status);

-- Insight Notes (micro-learnings)
CREATE TABLE IF NOT EXISTS insight_note (
    id SERIAL PRIMARY KEY,
    insight_type VARCHAR(100) NOT NULL,
    subject_type VARCHAR(50) NOT NULL,
    subject_id VARCHAR(100),
    insight_text TEXT NOT NULL,
    confidence VARCHAR(20) DEFAULT 'medium',
    evidence_sources JSONB,
    proposed_by VARCHAR(100) NOT NULL,
    proposed_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'proposed',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    merged_into_version_id INTEGER,
    merged_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_insight_note_subject ON insight_note(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_insight_note_status ON insight_note(status);

-- Review Queue (HITL gate)
CREATE TABLE IF NOT EXISTS review_queue (
    id SERIAL PRIMARY KEY,
    item_type VARCHAR(50) NOT NULL,
    item_id INTEGER NOT NULL,
    requested_by VARCHAR(100) NOT NULL,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    priority VARCHAR(20) DEFAULT 'normal',
    summary TEXT NOT NULL,
    diff_summary TEXT,
    evidence_summary TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    assigned_to VARCHAR(100),
    assigned_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(100),
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_item ON review_queue(item_type, item_id);

-- Prompt Fragments (dynamic system prompt pieces)
CREATE TABLE IF NOT EXISTS prompt_fragment (
    id SERIAL PRIMARY KEY,
    fragment_id VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL,
    trigger_condition JSONB,
    content TEXT NOT NULL,
    priority INT DEFAULT 50,
    user_id INT,
    namespace VARCHAR(100),
    status VARCHAR(20) DEFAULT 'draft',
    learned_from TEXT,
    learned_context TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system',
    approved_by VARCHAR(100),
    approved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_prompt_fragment_category ON prompt_fragment(category);
CREATE INDEX IF NOT EXISTS idx_prompt_fragment_status ON prompt_fragment(status);
CREATE INDEX IF NOT EXISTS idx_prompt_fragment_user_id ON prompt_fragment(user_id);
CREATE INDEX IF NOT EXISTS idx_prompt_fragment_namespace ON prompt_fragment(namespace);

-- Coach OS: User Profiles (versioned preferences)
CREATE TABLE IF NOT EXISTS user_profile (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    telegram_id BIGINT UNIQUE,
    name VARCHAR(255),

    -- Communication Preferences
    communication_style VARCHAR(50) DEFAULT 'direkt',
    response_length VARCHAR(20) DEFAULT 'mittel',
    language VARCHAR(10) DEFAULT 'de',

    -- ADHD Accommodations
    adhd_mode BOOLEAN DEFAULT FALSE,
    chunk_size VARCHAR(20) DEFAULT 'mittel',
    reminder_frequency VARCHAR(20) DEFAULT 'mittel',

    -- Energy Management
    energy_awareness BOOLEAN DEFAULT TRUE,
    default_energy_level VARCHAR(20) DEFAULT 'mittel',

    -- Coaching
    coaching_areas JSONB DEFAULT '[]',
    active_coaching_mode VARCHAR(50) DEFAULT 'coach',

    -- Context
    allowed_namespaces JSONB DEFAULT '["private"]',
    timezone VARCHAR(100) DEFAULT 'Europe/Zurich',

    -- Metadata
    current_version INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_profile_telegram_id ON user_profile(telegram_id);

-- User Profile Version History
CREATE TABLE IF NOT EXISTS user_profile_version (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user_profile(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    changes JSONB NOT NULL,
    changed_by VARCHAR(100) NOT NULL,
    change_reason TEXT,
    change_source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_upv_user_id ON user_profile_version(user_id);

-- User Feedback (for learning)
CREATE TABLE IF NOT EXISTS user_feedback (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES user_profile(id),
    feedback_type VARCHAR(50) NOT NULL,
    context JSONB,
    message_id VARCHAR(100),
    conversation_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_user_id ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_type ON user_feedback(feedback_type);

-- Coach OS: Tasks (lightweight task management)
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'blocked', 'done')),
    priority VARCHAR(20) DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    due_date DATE,
    context_tag VARCHAR(50) DEFAULT 'jarvis',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);

-- Task Notes
CREATE TABLE IF NOT EXISTS task_notes (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    source_refs JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_notes_task_id ON task_notes(task_id);

-- ============ Memory Hygiene: Knowledge Items with Relevance ============

-- Generic knowledge items with relevance scoring (v1 Memory Hygiene)
-- Enhanced with salience scoring (Phase 11)
CREATE TABLE IF NOT EXISTS knowledge_item (
    id SERIAL PRIMARY KEY,
    item_type VARCHAR(50) NOT NULL,          -- pattern, fact, preference, relationship_note
    namespace VARCHAR(50) NOT NULL,          -- private, work_projektil, work_visualfox
    subject_type VARCHAR(50),                -- person, org, project, self
    subject_id VARCHAR(100),                 -- person_id, org_id, etc.
    current_version_id INTEGER,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'archived', 'disputed')),
    relevance_score FLOAT DEFAULT 1.0,       -- 0.0-1.0, decays over time
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),  -- when last referenced
    last_reinforced_at TIMESTAMPTZ,          -- when last confirmed
    -- Salience scoring (Phase 11: outcome-based reinforcement)
    salience_score FLOAT DEFAULT 0.5,        -- 0.0-1.0, computed from components
    decision_impact FLOAT DEFAULT 0.0,       -- positive correlation with decision outcomes
    goal_relevance FLOAT DEFAULT 0.0,        -- relevance to active goals
    surprise_factor FLOAT DEFAULT 0.0,       -- novelty/unexpectedness
    salience_updated_at TIMESTAMPTZ,         -- when salience was last computed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ki_type_namespace ON knowledge_item(item_type, namespace);
CREATE INDEX IF NOT EXISTS idx_ki_subject ON knowledge_item(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_ki_status ON knowledge_item(status);
CREATE INDEX IF NOT EXISTS idx_ki_relevance ON knowledge_item(relevance_score);
CREATE INDEX IF NOT EXISTS idx_ki_salience ON knowledge_item(salience_score);

-- Knowledge item versions (immutable history)
CREATE TABLE IF NOT EXISTS knowledge_item_version (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES knowledge_item(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,                  -- the actual knowledge content
    confidence VARCHAR(20) DEFAULT 'medium', -- low, medium, high
    evidence_refs JSONB,                     -- links to evidence in Qdrant/Meilisearch
    created_by VARCHAR(100) NOT NULL,        -- user, jarvis, system
    created_at TIMESTAMPTZ DEFAULT NOW(),
    change_reason TEXT,
    UNIQUE(item_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_kiv_item_id ON knowledge_item_version(item_id);

-- ============ Decision Log for /decide_and_message ============

CREATE TABLE IF NOT EXISTS decision_log (
    id SERIAL PRIMARY KEY,
    decision_id VARCHAR(100) NOT NULL UNIQUE,
    namespace VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    context_summary TEXT,
    current_version_id INTEGER,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'decided', 'communicated', 'archived')),
    stakeholder_ids JSONB DEFAULT '[]',      -- list of person_ids affected
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    decided_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_dl_decision_id ON decision_log(decision_id);
CREATE INDEX IF NOT EXISTS idx_dl_namespace ON decision_log(namespace);
CREATE INDEX IF NOT EXISTS idx_dl_status ON decision_log(status);

CREATE TABLE IF NOT EXISTS decision_log_version (
    id SERIAL PRIMARY KEY,
    decision_id INTEGER NOT NULL REFERENCES decision_log(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,                  -- decision details, rationale
    stakeholder_messages JSONB,              -- per-stakeholder drafted messages
    evidence_refs JSONB,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(decision_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_dlv_decision_id ON decision_log_version(decision_id);

-- ============ Domain Access Log (for cross-namespace tracking) ============

CREATE TABLE IF NOT EXISTS domain_access_log (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    source_namespace VARCHAR(50) NOT NULL,
    target_namespace VARCHAR(50) NOT NULL,
    access_type VARCHAR(50) NOT NULL,        -- query, retrieve, inference
    item_type VARCHAR(50),
    item_id VARCHAR(100),
    allowed BOOLEAN NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dal_namespaces ON domain_access_log(source_namespace, target_namespace);
CREATE INDEX IF NOT EXISTS idx_dal_created ON domain_access_log(created_at);

-- ============ Jarvis Self-Model (Personality Consolidation) ============

-- Jarvis self-model for personality persistence across sessions
CREATE TABLE IF NOT EXISTS jarvis_self_model (
    id TEXT PRIMARY KEY DEFAULT 'default',

    -- What I've learned about myself
    strengths JSONB DEFAULT '[]',              -- ["coaching sessions work well", "sentiment detection reliable"]
    weaknesses JSONB DEFAULT '[]',             -- ["tool-calling loops", "sometimes too analytical"]
    wishes JSONB DEFAULT '[]',                 -- ["better pattern matching", "consolidation endpoint"]

    -- What I've learned about the user
    user_patterns JSONB DEFAULT '{}',          -- {"thinks_in_systems": true, "prefers_bullets": true}
    user_preferences JSONB DEFAULT '{}',       -- {"refinement_over_revolution": true}

    -- Current self-perception
    current_feeling TEXT,                      -- "well-calibrated system with occasional hiccups"
    confidence_level FLOAT DEFAULT 0.7,        -- 0.0-1.0

    -- Session stats
    total_sessions INTEGER DEFAULT 0,
    successful_interactions INTEGER DEFAULT 0,
    frustrating_moments INTEGER DEFAULT 0,

    -- Timestamps
    last_consolidation TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Self-model history (for tracking evolution)
CREATE TABLE IF NOT EXISTS jarvis_self_model_snapshot (
    id SERIAL PRIMARY KEY,
    model_id TEXT NOT NULL DEFAULT 'default',
    snapshot_reason TEXT,                      -- "weekly", "significant_learning", "user_feedback"
    strengths JSONB,
    weaknesses JSONB,
    wishes JSONB,
    user_patterns JSONB,
    current_feeling TEXT,
    confidence_level FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jsms_model ON jarvis_self_model_snapshot(model_id);
CREATE INDEX IF NOT EXISTS idx_jsms_created ON jarvis_self_model_snapshot(created_at DESC);

-- ============ Jarvis Configuration Tables ============
-- Personas, Modes, and Policies - all instance data in PostgreSQL

-- Personas define HOW Jarvis responds (tone, format, style)
CREATE TABLE IF NOT EXISTS jarvis_persona (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    intent TEXT,                               -- Brief description of persona purpose
    tone JSONB DEFAULT '{}',                   -- style, emoji_level, directness
    format JSONB DEFAULT '{}',                 -- headings, bullets, max_sections, length
    requirements JSONB DEFAULT '[]',           -- What this persona MUST do
    forbidden JSONB DEFAULT '[]',              -- What this persona must NEVER do
    example TEXT,                              -- One-liner example output
    is_default BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jp_active ON jarvis_persona(is_active);

-- Modes define WHAT Jarvis does (coach, analyst, mirror, etc.)
CREATE TABLE IF NOT EXISTS jarvis_mode (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT,                              -- What this mode is for
    output_contract JSONB DEFAULT '{}',        -- required_sections, optional_sections
    tone JSONB DEFAULT '{}',                   -- style, pacing, voice
    forbidden JSONB DEFAULT '[]',              -- What this mode must NEVER do
    citation_style TEXT,                       -- inline_subtle, explicit_with_dates, etc.
    unknown_response TEXT,                     -- What to say when info not found
    is_default BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jm_active ON jarvis_mode(is_active);

-- Policies define RULES Jarvis follows (system prompts, governance)
CREATE TABLE IF NOT EXISTS jarvis_policy (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'general',           -- system, governance, coaching, self, etc.
    content TEXT NOT NULL,                     -- The actual policy text (Markdown)
    priority INTEGER DEFAULT 100,              -- Higher = injected earlier in prompt
    inject_in_prompt BOOLEAN DEFAULT true,     -- Should this be in system prompt?
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jpol_category ON jarvis_policy(category);
CREATE INDEX IF NOT EXISTS idx_jpol_active ON jarvis_policy(is_active);
CREATE INDEX IF NOT EXISTS idx_jpol_priority ON jarvis_policy(priority DESC);

-- ============ User Profile (Micha) ============
-- Comprehensive profile of the Jarvis user - much richer than external person profiles

CREATE TABLE IF NOT EXISTS jarvis_user_profile (
    id TEXT PRIMARY KEY DEFAULT 'micha',

    -- Identity
    display_name TEXT NOT NULL DEFAULT 'Micha',
    roles JSONB DEFAULT '[]',                  -- ["CEO Projektil", "Freelancer VisualFox"]
    active_namespaces JSONB DEFAULT '["private", "work_projektil", "work_visualfox"]',

    -- Communication Preferences
    communication_prefs JSONB DEFAULT '{}',

    -- Work Preferences
    work_prefs JSONB DEFAULT '{}',

    -- Goals
    current_goals JSONB DEFAULT '[]',          -- [{id, title, priority, deadline, namespace}]
    long_term_goals JSONB DEFAULT '[]',
    anti_goals JSONB DEFAULT '[]',             -- What to consciously avoid

    -- ADHD-specific Patterns
    adhd_patterns JSONB DEFAULT '{}',

    -- Boundaries
    boundaries JSONB DEFAULT '{}',

    -- Relationship Context
    vip_contacts JSONB DEFAULT '[]',           -- IDs of most important contacts
    relationship_notes JSONB DEFAULT '{}',

    -- Learnings (what works / what doesn't)
    what_works JSONB DEFAULT '[]',
    what_fails JSONB DEFAULT '[]',
    milestones JSONB DEFAULT '[]',             -- Important learnings/achievements

    -- Meta
    confidence_level FLOAT DEFAULT 0.5,
    last_consolidation TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Profile Snapshots (for tracking evolution)
CREATE TABLE IF NOT EXISTS jarvis_user_profile_snapshot (
    id SERIAL PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'micha',
    snapshot_reason TEXT,                      -- "weekly", "goal_achieved", "manual"
    goals_snapshot JSONB,
    patterns_snapshot JSONB,
    learnings_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jups_profile ON jarvis_user_profile_snapshot(profile_id);
CREATE INDEX IF NOT EXISTS idx_jups_created ON jarvis_user_profile_snapshot(created_at DESC);

-- ============ Extended Person Profile Fields (v2) ============
-- Additional columns for person_profile to enable faster queries
-- These are added via ALTER TABLE in migrate_person_profile_v2()

-- ============ File Upload Queue ============
-- Tracks uploaded files through processing lifecycle

CREATE TABLE IF NOT EXISTS upload_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- File Info
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER,
    file_hash TEXT,                            -- SHA256 for dedup

    -- Source Info
    source_type TEXT NOT NULL,                 -- 'google_chat', 'whatsapp', 'email'
    namespace TEXT NOT NULL,                   -- 'private', 'work_projektil', 'work_visualfox'
    channel_hint TEXT,                         -- Optional: "Chat mit Patrik"

    -- Processing State
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'done', 'failed', 'archived')),
    priority INTEGER DEFAULT 3 CHECK (priority >= 1 AND priority <= 5),

    -- Results
    messages_extracted INTEGER,
    profiles_updated TEXT[],                   -- person_ids that were updated
    knowledge_items_created INTEGER,
    error_message TEXT,
    processing_log JSONB DEFAULT '[]',         -- Step-by-step log

    -- Timestamps
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    processing_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,

    -- Metadata
    uploaded_by TEXT DEFAULT 'api',            -- 'telegram', 'api', 'n8n'
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_uq_status ON upload_queue(status);
CREATE INDEX IF NOT EXISTS idx_uq_namespace ON upload_queue(namespace);
CREATE INDEX IF NOT EXISTS idx_uq_source_type ON upload_queue(source_type);
CREATE INDEX IF NOT EXISTS idx_uq_uploaded_at ON upload_queue(uploaded_at DESC);

-- ============ Chat Sync State (Incremental Processing) ============
-- Tracks processing checkpoints per channel for incremental imports

CREATE TABLE IF NOT EXISTS chat_sync_state (
    id TEXT PRIMARY KEY,                       -- "google_chat:work_projektil:space_abc"
    source_type TEXT NOT NULL,                 -- 'google_chat', 'whatsapp', 'email'
    namespace TEXT NOT NULL,                   -- 'private', 'work_projektil', 'work_visualfox'
    channel_id TEXT,                           -- Space/Group ID
    channel_name TEXT,                         -- Human readable name

    -- Checkpoint
    last_message_ts TIMESTAMPTZ,
    last_message_id TEXT,

    -- Stats
    total_messages_processed INTEGER DEFAULT 0,
    total_files_processed INTEGER DEFAULT 0,
    unique_participants TEXT[],                -- Detected person_ids

    -- Timestamps
    first_sync TIMESTAMPTZ,
    last_sync TIMESTAMPTZ,

    UNIQUE(source_type, namespace, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_css_source ON chat_sync_state(source_type);
CREATE INDEX IF NOT EXISTS idx_css_namespace ON chat_sync_state(namespace);
CREATE INDEX IF NOT EXISTS idx_css_last_sync ON chat_sync_state(last_sync DESC);

-- ============ Person Relationships ============
-- Explicit relationship tracking between persons

CREATE TABLE IF NOT EXISTS person_relationship (
    id SERIAL PRIMARY KEY,
    person_a_id TEXT NOT NULL,                 -- person_id
    person_b_id TEXT NOT NULL,                 -- person_id
    relationship_type TEXT NOT NULL,           -- 'colleague', 'friend', 'family', 'reports_to', 'manages'
    namespace TEXT NOT NULL,                   -- Context where relationship exists

    -- Attributes
    strength INTEGER DEFAULT 3 CHECK (strength >= 1 AND strength <= 5),
    sentiment TEXT DEFAULT 'neutral' CHECK (sentiment IN ('positive', 'neutral', 'tense', 'negative')),
    notes TEXT,

    -- Evidence
    evidence_refs JSONB DEFAULT '[]',
    confidence FLOAT DEFAULT 0.5,

    -- Timestamps
    first_observed TIMESTAMPTZ,
    last_observed TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(person_a_id, person_b_id, relationship_type, namespace)
);

CREATE INDEX IF NOT EXISTS idx_pr_person_a ON person_relationship(person_a_id);
CREATE INDEX IF NOT EXISTS idx_pr_person_b ON person_relationship(person_b_id);
CREATE INDEX IF NOT EXISTS idx_pr_type ON person_relationship(relationship_type);

-- ============ Communication Channel Preferences ============
-- Per-person channel preferences

CREATE TABLE IF NOT EXISTS person_channel_preference (
    id SERIAL PRIMARY KEY,
    person_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,                -- 'google_chat', 'whatsapp', 'email', 'call'
    namespace TEXT NOT NULL,

    -- Preferences
    is_preferred BOOLEAN DEFAULT FALSE,
    use_for_urgent BOOLEAN DEFAULT FALSE,
    typical_response_time TEXT,                -- 'immediate', 'same_day', 'days'
    best_times TEXT[],                         -- ['morning', 'afternoon']

    -- Observations
    avg_response_minutes INTEGER,
    message_count INTEGER DEFAULT 0,
    last_message_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(person_id, channel_type, namespace)
);

CREATE INDEX IF NOT EXISTS idx_pcp_person ON person_channel_preference(person_id);

-- ============ Prompt Blueprints (Versioned Templates with A/B Testing) ============

-- Blueprint templates for specific use cases (morning briefing, email draft, etc.)
CREATE TABLE IF NOT EXISTS prompt_blueprint (
    id SERIAL PRIMARY KEY,
    blueprint_id TEXT NOT NULL UNIQUE,         -- "morning_briefing_v1", "email_draft_formal"
    name TEXT NOT NULL,
    description TEXT,
    use_case TEXT NOT NULL,                    -- "briefing", "email", "decision", "coaching", "analysis"

    -- Template
    template TEXT NOT NULL,                    -- Prompt template with {{placeholders}}
    variables_schema JSONB DEFAULT '[]',       -- [{name, type, required, default, description}]

    -- Versioning
    current_version_id INTEGER,

    -- Status
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'deprecated', 'archived')),
    is_default BOOLEAN DEFAULT false,          -- Default blueprint for this use_case

    -- Metadata
    created_by TEXT DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pb_default ON prompt_blueprint(use_case) WHERE is_default = true;
CREATE INDEX IF NOT EXISTS idx_pb_use_case ON prompt_blueprint(use_case);
CREATE INDEX IF NOT EXISTS idx_pb_status ON prompt_blueprint(status);

-- Blueprint version history (immutable)
CREATE TABLE IF NOT EXISTS prompt_blueprint_version (
    id SERIAL PRIMARY KEY,
    blueprint_id INTEGER NOT NULL REFERENCES prompt_blueprint(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,

    -- Content
    template TEXT NOT NULL,
    variables_schema JSONB DEFAULT '[]',

    -- Change tracking
    changed_by TEXT NOT NULL,
    change_reason TEXT,
    change_type TEXT NOT NULL,                 -- "create", "edit", "optimize", "ab_winner"

    -- Performance metrics (populated over time)
    usage_count INTEGER DEFAULT 0,
    avg_quality_score FLOAT,                   -- 0.0-1.0 based on user feedback
    avg_tokens_used INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(blueprint_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_pbv_blueprint ON prompt_blueprint_version(blueprint_id);
CREATE INDEX IF NOT EXISTS idx_pbv_quality ON prompt_blueprint_version(avg_quality_score DESC NULLS LAST);

-- A/B Test definitions
CREATE TABLE IF NOT EXISTS ab_test (
    id SERIAL PRIMARY KEY,
    test_id TEXT NOT NULL UNIQUE,              -- "morning_briefing_tone_test_2026"
    name TEXT NOT NULL,
    description TEXT,

    -- Test setup
    blueprint_id INTEGER NOT NULL REFERENCES prompt_blueprint(id),
    variant_a_version INTEGER NOT NULL,        -- Blueprint version ID for variant A
    variant_b_version INTEGER NOT NULL,        -- Blueprint version ID for variant B
    traffic_split FLOAT DEFAULT 0.5,           -- 0.0-1.0, percentage going to variant B

    -- Success metrics
    success_metric TEXT NOT NULL,              -- "user_rating", "task_completion", "response_quality"
    min_samples INTEGER DEFAULT 30,            -- Minimum interactions before declaring winner
    confidence_threshold FLOAT DEFAULT 0.95,   -- Statistical confidence required

    -- Timing
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'paused', 'completed', 'cancelled')),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,

    -- Results
    winner_variant TEXT,                       -- "A", "B", or NULL if no winner
    winner_confidence FLOAT,
    conclusion_notes TEXT,

    created_by TEXT DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_abt_status ON ab_test(status);
CREATE INDEX IF NOT EXISTS idx_abt_blueprint ON ab_test(blueprint_id);

-- A/B Test user assignments (deterministic assignment based on user_id hash)
CREATE TABLE IF NOT EXISTS ab_test_assignment (
    id SERIAL PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES ab_test(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,                     -- User or session identifier
    variant TEXT NOT NULL CHECK (variant IN ('A', 'B')),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(test_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_abta_test ON ab_test_assignment(test_id);
CREATE INDEX IF NOT EXISTS idx_abta_user ON ab_test_assignment(user_id);

-- A/B Test results (outcome tracking per interaction)
CREATE TABLE IF NOT EXISTS ab_test_result (
    id SERIAL PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES ab_test(id) ON DELETE CASCADE,
    assignment_id INTEGER REFERENCES ab_test_assignment(id),

    -- Context
    user_id TEXT NOT NULL,
    variant TEXT NOT NULL CHECK (variant IN ('A', 'B')),
    conversation_id TEXT,
    message_id TEXT,

    -- Metrics
    quality_score FLOAT,                       -- User-provided rating 0.0-1.0
    task_completed BOOLEAN,
    tokens_used INTEGER,
    response_time_ms INTEGER,

    -- User feedback
    feedback_type TEXT,                        -- "thumbs_up", "thumbs_down", "explicit_rating"
    feedback_text TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_abtr_test ON ab_test_result(test_id);
CREATE INDEX IF NOT EXISTS idx_abtr_variant ON ab_test_result(test_id, variant);
CREATE INDEX IF NOT EXISTS idx_abtr_created ON ab_test_result(created_at DESC);

-- Blueprint usage log (for analytics)
CREATE TABLE IF NOT EXISTS blueprint_usage (
    id SERIAL PRIMARY KEY,
    blueprint_id INTEGER REFERENCES prompt_blueprint(id),
    version_id INTEGER REFERENCES prompt_blueprint_version(id),

    -- Context
    user_id TEXT,
    conversation_id TEXT,
    use_case TEXT,

    -- Variables used
    variables_provided JSONB,

    -- Results
    tokens_used INTEGER,
    quality_score FLOAT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bu_blueprint ON blueprint_usage(blueprint_id);
CREATE INDEX IF NOT EXISTS idx_bu_version ON blueprint_usage(version_id);
CREATE INDEX IF NOT EXISTS idx_bu_created ON blueprint_usage(created_at DESC);

-- ============ Coaching Domains ============

-- User's active domain state
CREATE TABLE IF NOT EXISTS user_domain_state (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    active_domain VARCHAR(100) NOT NULL DEFAULT 'general',
    switched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uds_user ON user_domain_state(user_id);

-- Domain coaching sessions
CREATE TABLE IF NOT EXISTS domain_session (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'active',
    goals JSONB DEFAULT '[]',
    notes TEXT,
    progress_pct INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ds_user ON domain_session(user_id);
CREATE INDEX IF NOT EXISTS idx_ds_domain ON domain_session(domain_id);
CREATE INDEX IF NOT EXISTS idx_ds_status ON domain_session(status);

-- Domain-specific goals
CREATE TABLE IF NOT EXISTS domain_goal (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    goal_title TEXT NOT NULL,
    goal_description TEXT,
    target_date DATE,
    progress_pct INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    milestones JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dg_user_domain ON domain_goal(user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_dg_status ON domain_goal(status);

-- Cross-domain insights
CREATE TABLE IF NOT EXISTS cross_domain_insight (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source_domain VARCHAR(100) NOT NULL,
    target_domain VARCHAR(100),
    insight_type VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cdi_user ON cross_domain_insight(user_id);
CREATE INDEX IF NOT EXISTS idx_cdi_source ON cross_domain_insight(source_domain);
CREATE INDEX IF NOT EXISTS idx_cdi_applied ON cross_domain_insight(applied);

-- User competency tracking per domain
CREATE TABLE IF NOT EXISTS user_competency (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    competency_name VARCHAR(255) NOT NULL,
    current_level INTEGER DEFAULT 1,
    target_level INTEGER,
    evidence JSONB DEFAULT '[]',
    last_assessed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, domain_id, competency_name)
);

CREATE INDEX IF NOT EXISTS idx_uc_user_domain ON user_competency(user_id, domain_id);

-- ============ Learning & Intelligence (Phase 5) ============

-- Coaching effectiveness metrics
CREATE TABLE IF NOT EXISTS coaching_effectiveness (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    metric_type VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ce_user_domain ON coaching_effectiveness(user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_ce_type ON coaching_effectiveness(metric_type);
CREATE INDEX IF NOT EXISTS idx_ce_created ON coaching_effectiveness(created_at DESC);

-- Competency assessments (history)
CREATE TABLE IF NOT EXISTS competency_assessment (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    competency_name VARCHAR(255) NOT NULL,
    assessed_level INTEGER NOT NULL,
    evidence TEXT,
    assessed_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ca_user_domain ON competency_assessment(user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_ca_competency ON competency_assessment(competency_name);
CREATE INDEX IF NOT EXISTS idx_ca_created ON competency_assessment(created_at DESC);

-- Scheduled coaching interactions
CREATE TABLE IF NOT EXISTS scheduled_interaction (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100),
    interaction_type VARCHAR(100) NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    content JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    executed_at TIMESTAMPTZ,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_si_user ON scheduled_interaction(user_id);
CREATE INDEX IF NOT EXISTS idx_si_scheduled ON scheduled_interaction(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_si_status ON scheduled_interaction(status);

-- Learning digest (weekly summaries)
CREATE TABLE IF NOT EXISTS learning_digest (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    digest_type VARCHAR(50) DEFAULT 'weekly',
    content JSONB NOT NULL,
    delivered BOOLEAN DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ld_user ON learning_digest(user_id);
CREATE INDEX IF NOT EXISTS idx_ld_period ON learning_digest(period_start, period_end);
"""


def init_schema():
    """Initialize knowledge layer schema"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            for statement in DDL_STATEMENTS.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
        log_with_context(logger, "info", "Knowledge schema initialized")
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to init schema", error=str(e))
        return False


def migrate_person_profile_v2() -> Dict:
    """
    Migrate person_profile table to v2 with extended fields.
    Safe to run multiple times - uses IF NOT EXISTS.

    Adds direct query fields to person_profile for faster lookups:
    - email_addresses, phone_numbers, aliases
    - relationship_type, closeness, trust_level (to Micha)
    - communication preferences
    - last_interaction tracking
    - confidence_score
    """
    migrations = []
    errors = []

    alter_statements = [
        # Identity fields
        ("aliases", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS aliases TEXT[]"),
        ("email_addresses", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS email_addresses TEXT[]"),
        ("phone_numbers", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS phone_numbers TEXT[]"),

        # Relationship to Micha (quick access)
        ("relationship_type", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS relationship_type TEXT"),  # friend, colleague, boss, client, family
        ("closeness", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS closeness INTEGER CHECK (closeness >= 1 AND closeness <= 5)"),
        ("trust_level", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS trust_level INTEGER CHECK (trust_level >= 1 AND trust_level <= 5)"),
        ("power_dynamic", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS power_dynamic TEXT CHECK (power_dynamic IN ('equal', 'micha_higher', 'micha_lower'))"),

        # Communication style (quick access)
        ("formality", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS formality TEXT CHECK (formality IN ('formal', 'semi_formal', 'informal', 'very_casual'))"),
        ("preferred_channel", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS preferred_channel TEXT"),  # google_chat, whatsapp, email

        # Interaction tracking
        ("last_interaction_at", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMPTZ"),
        ("total_messages_analyzed", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS total_messages_analyzed INTEGER DEFAULT 0"),

        # Confidence & Meta
        ("confidence_score", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS confidence_score FLOAT DEFAULT 0.5"),
        ("needs_review", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT TRUE"),
        ("is_vip", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS is_vip BOOLEAN DEFAULT FALSE"),
        ("birthday", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS birthday DATE"),

        # Namespaces where this person appears
        ("active_namespaces", "ALTER TABLE person_profile ADD COLUMN IF NOT EXISTS active_namespaces TEXT[]"),
    ]

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            for field_name, sql in alter_statements:
                try:
                    cur.execute(sql)
                    migrations.append(field_name)
                except Exception as e:
                    # Column might already exist with different constraints
                    if "already exists" not in str(e).lower():
                        errors.append(f"{field_name}: {str(e)[:100]}")

            # Add indexes for new fields
            index_statements = [
                "CREATE INDEX IF NOT EXISTS idx_pp_relationship ON person_profile(relationship_type)",
                "CREATE INDEX IF NOT EXISTS idx_pp_closeness ON person_profile(closeness DESC)",
                "CREATE INDEX IF NOT EXISTS idx_pp_last_interaction ON person_profile(last_interaction_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_pp_is_vip ON person_profile(is_vip) WHERE is_vip = TRUE",
                "CREATE INDEX IF NOT EXISTS idx_pp_birthday ON person_profile(birthday)",
                "CREATE INDEX IF NOT EXISTS idx_pp_needs_review ON person_profile(needs_review) WHERE needs_review = TRUE",
            ]

            for idx_sql in index_statements:
                try:
                    cur.execute(idx_sql)
                except Exception as e:
                    errors.append(f"index: {str(e)[:100]}")

        log_with_context(logger, "info", "Person profile v2 migration complete",
                        migrated=len(migrations), errors=len(errors))

        return {
            "status": "success" if not errors else "partial",
            "migrated_fields": migrations,
            "errors": errors
        }

    except Exception as e:
        log_with_context(logger, "error", "Person profile v2 migration failed", error=str(e))
        return {"status": "error", "error": str(e)}


# ============ Person Profile Content Schema (for JSONB) ============
# This documents the expected structure of person_profile_version.content

PERSON_PROFILE_CONTENT_SCHEMA = """
{
    "identity": {
        "display_name": "string",
        "aliases": ["string"],
        "email_addresses": ["string"],
        "phone_numbers": ["string"]
    },
    "organizations": [
        {
            "org_id": "string",           // "projektil", "visualfox", "private"
            "role": "string",             // "CEO", "Kollege", "Freund"
            "department": "string|null",
            "since": "date|null",
            "is_active": "boolean"
        }
    ],
    "relationship_to_micha": {
        "type": "friend|colleague|boss|client|family|acquaintance",
        "closeness": "1-5",
        "trust_level": "1-5",
        "power_dynamic": "equal|micha_higher|micha_lower",
        "shared_history": {
            "first_contact": "date|null",
            "key_moments": ["string"],
            "conflicts": ["string"],
            "inside_jokes": ["string"]
        }
    },
    "communication_style": {
        "languages": ["de", "en"],
        "primary_language": "de",
        "formality": "formal|semi_formal|informal|very_casual",
        "message_patterns": {
            "typical_length": "short|medium|long",
            "response_speed": "immediate|same_day|slow",
            "emoji_usage": "none|minimal|moderate|heavy",
            "greeting_style": "string",
            "sign_off_style": "string"
        },
        "preferences": {
            "best_contact_times": ["morgens", "abends"],
            "preferred_channels": {
                "urgent": "whatsapp|call|email",
                "normal": "whatsapp|email|google_chat",
                "casual": "whatsapp|google_chat"
            },
            "likes_voice_messages": "boolean",
            "prefers_calls_over_text": "boolean"
        },
        "triggers": {
            "positive": ["string"],       // "Lob fuer Details", "Tech-Diskussionen"
            "negative": ["string"],       // "Zeitdruck", "Unklarheit"
            "topics_to_avoid": ["string"]
        }
    },
    "personality": {
        "big_five": {
            "openness": "1-5|null",
            "conscientiousness": "1-5|null",
            "extraversion": "1-5|null",
            "agreeableness": "1-5|null",
            "neuroticism": "1-5|null"
        },
        "decision_style": "analytical|intuitive|collaborative|quick",
        "conflict_style": "avoiding|accommodating|competing|collaborating|compromising",
        "stress_indicators": ["string"],
        "strengths": ["string"],
        "growth_areas": ["string"]
    },
    "context": {
        "personal": {
            "birthday": "date|null",
            "family_situation": "string|null",
            "hobbies": ["string"],
            "current_life_phase": "string|null"
        },
        "professional": {
            "expertise_areas": ["string"],
            "current_projects": ["string"],
            "goals": ["string"],
            "challenges": ["string"]
        }
    },
    "interaction_history": {
        "last_interaction": "timestamp",
        "total_messages_analyzed": "integer",
        "sentiment_trend": "improving|stable|declining",
        "recent_topics": ["string"],
        "pending_items": ["string"]
    },
    "meta": {
        "confidence_score": "0.0-1.0",
        "needs_review": "boolean",
        "sources": [
            {
                "source_type": "google_chat|whatsapp|email|manual",
                "namespace": "string",
                "message_count": "integer",
                "date_range": {"from": "date", "to": "date"}
            }
        ]
    }
}
"""


# ============ Person Profile Functions ============

def get_person_profile(person_id: str, approved_only: bool = True) -> Optional[Dict]:
    """Get current approved profile for a person"""
    try:
        with safe_list_query(timeout=10, table='person_profile') as cur:
            # Get base profile with current version
            cur.execute("""
                SELECT p.*, v.content, v.version_number, v.status as version_status,
                       v.changed_by, v.change_reason, v.created_at as version_created_at
                FROM person_profile p
                LEFT JOIN person_profile_version v ON p.current_version_id = v.id
                WHERE p.person_id = %s
            """, (person_id,))

            row = cur.fetchone()
            if not row:
                return None

            # If approved_only and version not approved, return None
            if approved_only and row.get("version_status") != "approved":
                return None

            return dict(row)
    except Exception as e:
        log_with_context(logger, "error", "Failed to get person profile",
                        person_id=person_id, error=str(e))
        return None


def get_all_person_profiles(status: str = "active") -> List[Dict]:
    """Get all person profiles"""
    try:
        with safe_list_query(timeout=10, table='person_profile') as cur:
            cur.execute("""
                SELECT p.person_id, p.name, p.org, p.status, p.profile_type,
                       v.version_number, v.status as version_status
                FROM person_profile p
                LEFT JOIN person_profile_version v ON p.current_version_id = v.id
                WHERE p.status = %s OR %s = 'all'
                ORDER BY p.name
            """, (status, status))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get all profiles", error=str(e))
        return []


def get_profile_versions(person_id: str, status: str = None) -> List[Dict]:
    """Get version history for a person profile"""
    try:
        with safe_list_query(timeout=10, table='person_profile_version') as cur:
            query = """
                SELECT v.*
                FROM person_profile_version v
                JOIN person_profile p ON v.profile_id = p.id
                WHERE p.person_id = %s
            """
            params = [person_id]

            if status:
                query += " AND v.status = %s"
                params.append(status)

            query += " ORDER BY v.version_number DESC"

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get profile versions",
                        person_id=person_id, error=str(e))
        return []


def propose_profile_change(
    person_id: str,
    content: Dict,
    changed_by: str,
    change_reason: str,
    evidence_sources: List[Dict] = None,
    auto_approve: bool = False
) -> Optional[int]:
    """
    Propose a change to a person profile (creates new version).
    Returns version_id.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get or create base profile
            cur.execute("SELECT id FROM person_profile WHERE person_id = %s", (person_id,))
            row = cur.fetchone()

            if row:
                profile_id = row["id"]
                # Get next version number
                cur.execute("""
                    SELECT COALESCE(MAX(version_number), 0) + 1 as next_version
                    FROM person_profile_version WHERE profile_id = %s
                """, (profile_id,))
                next_version = cur.fetchone()["next_version"]
            else:
                # Create new profile
                cur.execute("""
                    INSERT INTO person_profile (person_id, name, org, profile_type, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    person_id,
                    content.get("name", person_id),
                    content.get("org"),
                    content.get("type", "internal"),
                    changed_by
                ))
                profile_id = cur.fetchone()["id"]
                next_version = 1

            # Determine status
            status = "approved" if auto_approve else "proposed"
            reviewed_by = changed_by if auto_approve else None
            reviewed_at = "NOW()" if auto_approve else None

            # Create version
            cur.execute("""
                INSERT INTO person_profile_version
                (profile_id, version_number, content, changed_by, change_reason,
                 change_type, evidence_sources, status, reviewed_by, reviewed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                profile_id,
                next_version,
                json.dumps(content),
                changed_by,
                change_reason,
                "jarvis_proposal" if changed_by == "jarvis" else "human_edit",
                json.dumps(evidence_sources) if evidence_sources else None,
                status,
                reviewed_by,
                datetime.now() if auto_approve else None
            ))
            version_id = cur.fetchone()["id"]

            # If auto-approved, update current version pointer
            if auto_approve:
                cur.execute("""
                    UPDATE person_profile
                    SET current_version_id = %s, updated_at = NOW()
                    WHERE id = %s
                """, (version_id, profile_id))

            log_with_context(logger, "info", "Profile change proposed",
                           person_id=person_id, version_id=version_id, status=status)
            return version_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to propose profile change",
                        person_id=person_id, error=str(e))
        return None


def approve_profile_version(version_id: int, reviewed_by: str, note: str = None) -> bool:
    """Approve a proposed profile version"""
    try:
        with safe_write_query(timeout=15, table='person_profile_version') as cur:
            # Update version status
            cur.execute("""
                UPDATE person_profile_version
                SET status = 'approved', reviewed_by = %s, reviewed_at = NOW(), review_note = %s
                WHERE id = %s AND status = 'proposed'
                RETURNING profile_id
            """, (reviewed_by, note, version_id))

            row = cur.fetchone()
            if not row:
                return False

            profile_id = row["profile_id"]

            # Mark previous approved versions as superseded
            cur.execute("""
                UPDATE person_profile_version
                SET status = 'superseded'
                WHERE profile_id = %s AND status = 'approved' AND id != %s
            """, (profile_id, version_id))

            # Update current version pointer
            cur.execute("""
                UPDATE person_profile
                SET current_version_id = %s, updated_at = NOW()
                WHERE id = %s
            """, (version_id, profile_id))

            log_with_context(logger, "info", "Profile version approved",
                           version_id=version_id, reviewed_by=reviewed_by)
            return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to approve version",
                        version_id=version_id, error=str(e))
        return False


def reject_profile_version(version_id: int, reviewed_by: str, note: str = None) -> bool:
    """Reject a proposed profile version"""
    try:
        with safe_write_query(timeout=15, table='person_profile_version') as cur:
            cur.execute("""
                UPDATE person_profile_version
                SET status = 'rejected', reviewed_by = %s, reviewed_at = NOW(), review_note = %s
                WHERE id = %s AND status = 'proposed'
            """, (reviewed_by, note, version_id))

            log_with_context(logger, "info", "Profile version rejected",
                           version_id=version_id, reviewed_by=reviewed_by)
            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to reject version",
                        version_id=version_id, error=str(e))
        return False


def activate_profile(person_id: str) -> bool:
    """
    Activate a draft profile after approval.
    Changes profile status from 'draft' to 'active'.
    """
    try:
        with safe_write_query(timeout=15, table='person_profile') as cur:
            cur.execute("""
                UPDATE person_profile
                SET status = 'active', updated_at = NOW()
                WHERE person_id = %s AND status = 'draft'
            """, (person_id,))

            if cur.rowcount > 0:
                log_with_context(logger, "info", "Profile activated",
                               person_id=person_id)
                return True
            return False

    except Exception as e:
        log_with_context(logger, "error", "Failed to activate profile",
                        person_id=person_id, error=str(e))
        return False


# ============ Persona Style Functions ============

def get_persona_style(persona_id: str) -> Optional[Dict]:
    """Get current approved persona style"""
    try:
        with safe_list_query(timeout=10, table='persona_style') as cur:
            cur.execute("""
                SELECT p.*, v.content, v.version_number
                FROM persona_style p
                LEFT JOIN persona_style_version v ON p.current_version_id = v.id
                WHERE p.persona_id = %s AND v.status = 'approved'
            """, (persona_id,))

            row = cur.fetchone()
            return dict(row) if row else None

    except Exception as e:
        log_with_context(logger, "error", "Failed to get persona style",
                        persona_id=persona_id, error=str(e))
        return None


def get_all_persona_styles() -> List[Dict]:
    """Get all persona styles"""
    try:
        with safe_list_query(timeout=10, table='persona_style') as cur:
            cur.execute("""
                SELECT p.persona_id, p.name, p.is_default, p.status,
                       v.version_number, v.content->>'intent' as intent
                FROM persona_style p
                LEFT JOIN persona_style_version v ON p.current_version_id = v.id
                WHERE p.status = 'active'
                ORDER BY p.is_default DESC, p.name
            """)
            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get all personas", error=str(e))
        return []


# ============ Insight Functions ============

def propose_insight(
    insight_type: str,
    subject_type: str,
    subject_id: str,
    insight_text: str,
    confidence: str = "medium",
    evidence_sources: List[Dict] = None,
    proposed_by: str = "jarvis"
) -> Optional[int]:
    """Propose a new insight for review"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO insight_note
                (insight_type, subject_type, subject_id, insight_text,
                 confidence, evidence_sources, proposed_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                insight_type,
                subject_type,
                subject_id,
                insight_text,
                confidence,
                json.dumps(evidence_sources) if evidence_sources else None,
                proposed_by
            ))

            insight_id = cur.fetchone()["id"]
            log_with_context(logger, "info", "Insight proposed",
                           insight_id=insight_id, insight_type=insight_type)
            return insight_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to propose insight", error=str(e))
        return None


def get_insights(
    status: str = "pending",
    subject_type: str = None,
    subject_id: str = None,
    limit: int = 50
) -> List[Dict]:
    """Get insights by status and optional filters"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = "SELECT * FROM insight_note WHERE 1=1"
            params = []

            if status and status != "all":
                query += " AND status = %s"
                params.append(status)
            if subject_type:
                query += " AND subject_type = %s"
                params.append(subject_type)
            if subject_id:
                query += " AND subject_id = %s"
                params.append(subject_id)

            query += " ORDER BY proposed_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get insights", error=str(e))
        return []


def approve_insight(insight_id: int, reviewed_by: str, note: str = None) -> bool:
    """Approve an insight"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE insight_note
                SET status = 'approved', reviewed_by = %s, reviewed_at = NOW(), review_note = %s
                WHERE id = %s AND status = 'proposed'
            """, (reviewed_by, note, insight_id))

            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to approve insight",
                        insight_id=insight_id, error=str(e))
        return False


def reject_insight(insight_id: int, reviewed_by: str, note: str = None) -> bool:
    """Reject an insight"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE insight_note
                SET status = 'rejected', reviewed_by = %s, reviewed_at = NOW(), review_note = %s
                WHERE id = %s AND status = 'proposed'
            """, (reviewed_by, note, insight_id))

            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to reject insight",
                        insight_id=insight_id, error=str(e))
        return False


# ============ Review Queue Functions ============

def add_to_review_queue(
    item_type: str,
    item_id: int,
    summary: str,
    requested_by: str = "jarvis",
    priority: str = "normal",
    diff_summary: str = None,
    evidence_summary: str = None
) -> Optional[int]:
    """Add item to HITL review queue"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO review_queue
                (item_type, item_id, summary, requested_by, priority, diff_summary, evidence_summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (item_type, item_id, summary, requested_by, priority, diff_summary, evidence_summary))

            queue_id = cur.fetchone()["id"]
            log_with_context(logger, "info", "Added to review queue",
                           queue_id=queue_id, item_type=item_type)
            return queue_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to add to review queue", error=str(e))
        return None


def get_review_queue(
    status: str = "pending",
    item_type: str = None,
    limit: int = 20
) -> List[Dict]:
    """Get items in review queue"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = "SELECT * FROM review_queue WHERE 1=1"
            params = []

            if status and status != "all":
                query += " AND status = %s"
                params.append(status)
            if item_type:
                query += " AND item_type = %s"
                params.append(item_type)

            query += " ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, requested_at ASC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get review queue", error=str(e))
        return []


def process_review(
    queue_id: int,
    action: str,
    resolved_by: str,
    resolution_note: str = None
) -> bool:
    """Process a review queue item (approve or reject)"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get the item details
            cur.execute("SELECT item_type, item_id FROM review_queue WHERE id = %s", (queue_id,))
            row = cur.fetchone()
            if not row:
                return False

            item_type = row["item_type"]
            item_id = row["item_id"]

            # Update the underlying item
            if action == "approve":
                if item_type == "profile_version":
                    approve_profile_version(item_id, resolved_by, resolution_note)
                elif item_type == "insight":
                    approve_insight(item_id, resolved_by, resolution_note)
                new_status = "approved"
            else:
                if item_type == "profile_version":
                    reject_profile_version(item_id, resolved_by, resolution_note)
                elif item_type == "insight":
                    reject_insight(item_id, resolved_by, resolution_note)
                new_status = "rejected"

            # Update queue item
            cur.execute("""
                UPDATE review_queue
                SET status = %s, resolved_at = NOW(), resolved_by = %s, resolution_note = %s
                WHERE id = %s
            """, (new_status, resolved_by, resolution_note, queue_id))

            log_with_context(logger, "info", "Review processed",
                           queue_id=queue_id, action=action, resolved_by=resolved_by)
            return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to process review",
                        queue_id=queue_id, error=str(e))
        return False


# ============ Migration Functions ============

def migrate_json_profiles(profiles_dir: str) -> Dict[str, Any]:
    """Migrate existing JSON profiles to Postgres as initial approved seeds"""
    from pathlib import Path

    migrated = []
    errors = []

    profiles_path = Path(profiles_dir)
    if not profiles_path.exists():
        return {"count": 0, "migrated": [], "errors": [f"Directory not found: {profiles_dir}"]}

    for json_file in profiles_path.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                content = json.load(f)

            person_id = json_file.stem

            with get_conn() as conn:
                cur = conn.cursor()

                # Create base profile record
                cur.execute("""
                    INSERT INTO person_profile
                    (person_id, name, org, profile_type, languages, timezone, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (person_id) DO UPDATE SET updated_at = NOW()
                    RETURNING id
                """, (
                    person_id,
                    content.get("name", person_id),
                    content.get("org"),
                    content.get("type", "internal"),
                    json.dumps(content.get("languages", ["de"])),
                    content.get("timezone", "Europe/Zurich"),
                    content.get("status", "active"),
                    "system:migration"
                ))
                profile_id = cur.fetchone()["id"]

                # Create initial version (pre-approved)
                cur.execute("""
                    INSERT INTO person_profile_version
                    (profile_id, version_number, content, changed_by, change_reason,
                     change_type, status, reviewed_by, reviewed_at)
                    VALUES (%s, 1, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (profile_id, version_number) DO NOTHING
                    RETURNING id
                """, (
                    profile_id,
                    json.dumps(content),
                    "system:migration",
                    f"Initial seed from {json_file.name}",
                    "initial_seed",
                    "approved",
                    "system:migration"
                ))

                version_row = cur.fetchone()
                if version_row:
                    version_id = version_row["id"]
                    # Update current version pointer
                    cur.execute("""
                        UPDATE person_profile SET current_version_id = %s WHERE id = %s
                    """, (version_id, profile_id))

                migrated.append(person_id)
                log_with_context(logger, "info", "Migrated profile", person_id=person_id)

        except Exception as e:
            errors.append({"file": str(json_file), "error": str(e)})
            log_with_context(logger, "error", "Failed to migrate profile",
                           file=str(json_file), error=str(e))

    return {
        "count": len(migrated),
        "migrated": migrated,
        "errors": errors
    }


def migrate_json_personas(personas_file: str) -> Dict[str, Any]:
    """Migrate existing personas JSON to Postgres as initial approved seeds"""
    from pathlib import Path

    migrated = []
    errors = []

    personas_path = Path(personas_file)
    if not personas_path.exists():
        return {"count": 0, "migrated": [], "errors": [f"File not found: {personas_file}"]}

    try:
        with open(personas_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        default_persona_id = config.get("default_persona_id", "micha_default")
        personas = config.get("personas", [])

        # Handle both array and dict formats
        if isinstance(personas, dict):
            personas_list = [{"id": k, **v} for k, v in personas.items()]
        else:
            personas_list = personas

        for persona_data in personas_list:
            try:
                persona_id = persona_data.get("id")
                if not persona_id:
                    continue

                with get_conn() as conn:
                    cur = conn.cursor()

                    # Create base persona record
                    cur.execute("""
                        INSERT INTO persona_style
                        (persona_id, name, is_default, status)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (persona_id) DO UPDATE SET updated_at = NOW()
                        RETURNING id
                    """, (
                        persona_id,
                        persona_data.get("name", persona_id),
                        persona_id == default_persona_id,
                        "active"
                    ))
                    style_id = cur.fetchone()["id"]

                    # Create initial version
                    cur.execute("""
                        INSERT INTO persona_style_version
                        (persona_id, version_number, content, changed_by, change_reason,
                         change_type, status, reviewed_by, reviewed_at)
                        VALUES (%s, 1, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (persona_id, version_number) DO NOTHING
                        RETURNING id
                    """, (
                        style_id,
                        json.dumps(persona_data),
                        "system:migration",
                        "Initial seed from persona_profiles.json",
                        "initial_seed",
                        "approved",
                        "system:migration"
                    ))

                    version_row = cur.fetchone()
                    if version_row:
                        version_id = version_row["id"]
                        cur.execute("""
                            UPDATE persona_style SET current_version_id = %s WHERE id = %s
                        """, (version_id, style_id))

                    migrated.append(persona_id)
                    log_with_context(logger, "info", "Migrated persona", persona_id=persona_id)

            except Exception as e:
                errors.append({"persona": persona_id, "error": str(e)})

    except Exception as e:
        errors.append({"file": personas_file, "error": str(e)})

    return {
        "count": len(migrated),
        "migrated": migrated,
        "errors": errors
    }


# ============ Prompt Fragment Functions ============

def create_prompt_fragment(
    category: str,
    content: str,
    trigger_condition: Dict = None,
    priority: int = 50,
    user_id: int = None,
    namespace: str = None,
    status: str = "draft",
    learned_from: str = None,
    learned_context: str = None,
    created_by: str = "system"
) -> Optional[int]:
    """
    Create a new prompt fragment.

    Categories:
    - user_pref: User preferences (e.g., "kurze Antworten")
    - namespace: Namespace-specific rules
    - persona: Persona additions
    - sentiment: Sentiment-triggered instructions
    - pattern: Pattern-based context
    - capability: Capability awareness

    Returns: fragment_id or None on error
    """
    import hashlib

    # Generate unique fragment_id
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
    fragment_id = f"{category}_{ts}_{content_hash}"

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO prompt_fragment
                (fragment_id, category, trigger_condition, content, priority,
                 user_id, namespace, status, learned_from, learned_context, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                fragment_id,
                category,
                json.dumps(trigger_condition) if trigger_condition else None,
                content,
                priority,
                user_id,
                namespace,
                status,
                learned_from,
                learned_context,
                created_by
            ))

            db_id = cur.fetchone()["id"]
            log_with_context(logger, "info", "Prompt fragment created",
                           fragment_id=fragment_id, category=category, status=status)
            return db_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to create prompt fragment", error=str(e))
        return None


def get_prompt_fragments(
    category: str = None,
    user_id: int = None,
    namespace: str = None,
    status: str = "approved",
    include_global: bool = True
) -> List[Dict]:
    """
    Get prompt fragments matching criteria.

    Args:
        category: Filter by category
        user_id: Filter by user (None = global only)
        namespace: Filter by namespace (None = all namespaces)
        status: Filter by status (default: approved)
        include_global: Include user_id=NULL fragments

    Returns: List of fragments ordered by priority DESC
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = "SELECT * FROM prompt_fragment WHERE 1=1"
            params = []

            if status and status != "all":
                query += " AND status = %s"
                params.append(status)

            if category:
                query += " AND category = %s"
                params.append(category)

            # User filtering with optional global
            if user_id is not None:
                if include_global:
                    query += " AND (user_id = %s OR user_id IS NULL)"
                else:
                    query += " AND user_id = %s"
                params.append(user_id)
            else:
                # Only global fragments
                query += " AND user_id IS NULL"

            # Namespace filtering
            if namespace:
                query += " AND (namespace = %s OR namespace IS NULL)"
                params.append(namespace)
            else:
                query += " AND namespace IS NULL"

            query += " ORDER BY priority DESC, created_at ASC"

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get prompt fragments", error=str(e))
        return []


def get_prompt_fragment_by_id(fragment_id: str) -> Optional[Dict]:
    """Get a single prompt fragment by fragment_id"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_fragment WHERE fragment_id = %s",
                (fragment_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    except Exception as e:
        log_with_context(logger, "error", "Failed to get prompt fragment",
                        fragment_id=fragment_id, error=str(e))
        return None


def approve_prompt_fragment(fragment_id: str, approved_by: str) -> bool:
    """Approve a draft prompt fragment"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE prompt_fragment
                SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                WHERE fragment_id = %s AND status = 'draft'
            """, (approved_by, fragment_id))

            success = cur.rowcount > 0
            if success:
                log_with_context(logger, "info", "Prompt fragment approved",
                               fragment_id=fragment_id, approved_by=approved_by)
            return success

    except Exception as e:
        log_with_context(logger, "error", "Failed to approve prompt fragment",
                        fragment_id=fragment_id, error=str(e))
        return False


def disable_prompt_fragment(fragment_id: str, disabled_by: str) -> bool:
    """Disable a prompt fragment"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE prompt_fragment
                SET status = 'disabled', updated_at = NOW()
                WHERE fragment_id = %s
            """, (fragment_id,))

            success = cur.rowcount > 0
            if success:
                log_with_context(logger, "info", "Prompt fragment disabled",
                               fragment_id=fragment_id, disabled_by=disabled_by)
            return success

    except Exception as e:
        log_with_context(logger, "error", "Failed to disable prompt fragment",
                        fragment_id=fragment_id, error=str(e))
        return False


def delete_prompt_fragment(fragment_id: str) -> bool:
    """Delete a prompt fragment (only if draft)"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM prompt_fragment
                WHERE fragment_id = %s AND status = 'draft'
            """, (fragment_id,))

            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to delete prompt fragment",
                        fragment_id=fragment_id, error=str(e))
        return False


def get_triggered_fragments(
    sentiment_result: Dict = None,
    namespace: str = None,
    user_id: int = None
) -> List[Dict]:
    """
    Get fragments that match current context triggers.

    Evaluates trigger_condition against sentiment_result.

    Args:
        sentiment_result: Result from sentiment_analyzer (optional)
        namespace: Current namespace
        user_id: Current user ID

    Returns: List of matching fragments
    """
    # Get all approved fragments for this user/namespace
    fragments = get_prompt_fragments(
        user_id=user_id,
        namespace=namespace,
        status="approved",
        include_global=True
    )

    if not sentiment_result:
        # Return all non-triggered fragments
        return [f for f in fragments if not f.get("trigger_condition")]

    matched = []
    for fragment in fragments:
        trigger = fragment.get("trigger_condition")
        if not trigger:
            # No trigger = always include
            matched.append(fragment)
            continue

        # Parse trigger as JSON if string
        if isinstance(trigger, str):
            try:
                trigger = json.loads(trigger)
            except Exception as e:
                log_with_context(logger, "error", "Failed to parse trigger JSON", error=str(e), fragment_id=fragment.get("fragment_id"))
                continue

        # Evaluate trigger conditions
        if _matches_trigger(trigger, sentiment_result):
            matched.append(fragment)

    return matched


def _matches_trigger(trigger: Dict, sentiment: Dict) -> bool:
    """Check if sentiment matches trigger condition"""

    # Check dominant sentiment
    if "dominant" in trigger:
        if sentiment.get("dominant") != trigger["dominant"]:
            return False

    # Check alert level
    if "alert_level" in trigger:
        levels = ["none", "low", "medium", "high"]
        required_idx = levels.index(trigger["alert_level"]) if trigger["alert_level"] in levels else 0
        actual_idx = levels.index(sentiment.get("alert_level", "none")) if sentiment.get("alert_level") in levels else 0
        if actual_idx < required_idx:
            return False

    # Check minimum scores
    for score_key in ["urgency_score", "stress_score", "frustration_score", "positive_score"]:
        min_key = f"min_{score_key}"
        if min_key in trigger:
            if sentiment.get(score_key, 0) < trigger[min_key]:
                return False

    return True


# ============ Coach OS: User Profile Functions ============

def get_user_profile(user_id: int = None, telegram_id: int = None) -> Optional[Dict]:
    """
    Get user profile by user_id or telegram_id.

    Returns: User profile dict or None
    """
    if not user_id and not telegram_id:
        return None

    if telegram_id is not None:
        try:
            telegram_id = int(telegram_id)
        except Exception:
            return None

    if user_id is not None:
        try:
            user_id = int(user_id)
        except Exception:
            return None

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            if user_id:
                cur.execute("SELECT * FROM user_profile WHERE user_id = %s", (user_id,))
            else:
                cur.execute("SELECT * FROM user_profile WHERE telegram_id = %s", (telegram_id,))

            row = cur.fetchone()
            return dict(row) if row else None

    except Exception as e:
        log_with_context(logger, "error", "Failed to get user profile",
                        user_id=user_id, telegram_id=telegram_id, error=str(e))
        return None


def get_or_create_user_profile(
    telegram_id: int,
    name: str = None,
    defaults: Dict = None
) -> Dict:
    """
    Get or create a user profile for a Telegram user.

    Args:
        telegram_id: Telegram user ID
        name: User's name
        defaults: Default values for new profile

    Returns: User profile dict
    """
    try:
        telegram_id = int(telegram_id)
        with get_conn() as conn:
            cur = conn.cursor()

            # Try to get existing profile
            cur.execute("SELECT * FROM user_profile WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()

            if row:
                return dict(row)

            # Create new profile
            defaults = defaults or {}

            # Get next user_id
            cur.execute("SELECT COALESCE(MAX(user_id), 0) + 1 as next_id FROM user_profile")
            next_user_id = cur.fetchone()["next_id"]

            cur.execute("""
                INSERT INTO user_profile
                (user_id, telegram_id, name, communication_style, response_length,
                 language, adhd_mode, chunk_size, reminder_frequency,
                 energy_awareness, default_energy_level, coaching_areas,
                 active_coaching_mode, allowed_namespaces, timezone)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                next_user_id,
                telegram_id,
                name or f"User_{telegram_id}",
                defaults.get("communication_style", "direkt"),
                defaults.get("response_length", "mittel"),
                defaults.get("language", "de"),
                defaults.get("adhd_mode", False),
                defaults.get("chunk_size", "mittel"),
                defaults.get("reminder_frequency", "mittel"),
                defaults.get("energy_awareness", True),
                defaults.get("default_energy_level", "mittel"),
                json.dumps(defaults.get("coaching_areas", [])),
                defaults.get("active_coaching_mode", "coach"),
                json.dumps(defaults.get("allowed_namespaces", ["private"])),
                defaults.get("timezone", "Europe/Zurich")
            ))

            new_profile = dict(cur.fetchone())
            log_with_context(logger, "info", "User profile created",
                           user_id=next_user_id, telegram_id=telegram_id)
            return new_profile

    except Exception as e:
        log_with_context(logger, "error", "Failed to get/create user profile",
                        telegram_id=telegram_id, error=str(e))
        # Return minimal default profile
        return {
            "user_id": 0,
            "telegram_id": telegram_id,
            "name": name,
            "adhd_mode": False,
            "communication_style": "direkt",
            "response_length": "mittel",
            "active_coaching_mode": "coach"
        }


def update_user_profile(
    user_id: int,
    updates: Dict,
    changed_by: str = "user",
    change_reason: str = None
) -> bool:
    """
    Update user profile and create version history.

    Args:
        user_id: User's internal ID
        updates: Dict of fields to update
        changed_by: Who made the change (user, jarvis, system)
        change_reason: Reason for change

    Returns: True if successful
    """
    # Allowed fields for update
    ALLOWED_FIELDS = {
        "name", "communication_style", "response_length", "language",
        "adhd_mode", "chunk_size", "reminder_frequency",
        "energy_awareness", "default_energy_level",
        "coaching_areas", "active_coaching_mode",
        "allowed_namespaces", "timezone"
    }

    # Filter to allowed fields
    valid_updates = {k: v for k, v in updates.items() if k in ALLOWED_FIELDS}
    if not valid_updates:
        return False

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current profile
            cur.execute("SELECT * FROM user_profile WHERE user_id = %s", (user_id,))
            current = cur.fetchone()
            if not current:
                return False

            current_version = current["current_version"]

            # Build SET clause
            set_parts = []
            params = []
            for field, value in valid_updates.items():
                if field in ("coaching_areas", "allowed_namespaces"):
                    set_parts.append(f"{field} = %s")
                    params.append(json.dumps(value) if not isinstance(value, str) else value)
                else:
                    set_parts.append(f"{field} = %s")
                    params.append(value)

            set_parts.append("current_version = %s")
            params.append(current_version + 1)

            set_parts.append("updated_at = NOW()")

            params.append(user_id)

            # Update profile
            cur.execute(f"""
                UPDATE user_profile
                SET {", ".join(set_parts)}
                WHERE user_id = %s
            """, params)

            # Create version record
            cur.execute("""
                INSERT INTO user_profile_version
                (user_id, version_number, changes, changed_by, change_reason, change_source)
                VALUES (
                    (SELECT id FROM user_profile WHERE user_id = %s),
                    %s, %s, %s, %s, %s
                )
            """, (
                user_id,
                current_version + 1,
                json.dumps(valid_updates),
                changed_by,
                change_reason,
                "api"
            ))

            log_with_context(logger, "info", "User profile updated",
                           user_id=user_id, fields=list(valid_updates.keys()),
                           new_version=current_version + 1)
            return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to update user profile",
                        user_id=user_id, error=str(e))
        return False


def get_user_profile_history(user_id: int, limit: int = 10) -> List[Dict]:
    """Get version history for a user profile"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT v.*
                FROM user_profile_version v
                JOIN user_profile p ON v.user_id = p.id
                WHERE p.user_id = %s
                ORDER BY v.version_number DESC
                LIMIT %s
            """, (user_id, limit))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get profile history",
                        user_id=user_id, error=str(e))
        return []


def record_user_feedback(
    user_id: int,
    feedback_type: str,
    context: Dict = None,
    message_id: str = None,
    conversation_id: str = None
) -> Optional[int]:
    """
    Record user feedback for learning.

    Feedback types:
    - response_good: User liked the response
    - response_too_long: Response was too verbose
    - response_too_short: Response was too brief
    - response_unclear: Response was confusing
    - style_change: User requested style change
    - adhd_helpful: ADHD accommodations were helpful
    - adhd_unhelpful: ADHD accommodations weren't helpful

    Returns: feedback_id or None
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get internal id from user_id
            cur.execute("SELECT id FROM user_profile WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            internal_id = row["id"] if row else None

            cur.execute("""
                INSERT INTO user_feedback
                (user_id, feedback_type, context, message_id, conversation_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                internal_id,
                feedback_type,
                json.dumps(context) if context else None,
                message_id,
                conversation_id
            ))

            feedback_id = cur.fetchone()["id"]
            log_with_context(logger, "info", "User feedback recorded",
                           feedback_id=feedback_id, feedback_type=feedback_type)
            return feedback_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to record feedback",
                        user_id=user_id, error=str(e))
        return None


def get_user_feedback_stats(user_id: int) -> Dict:
    """Get aggregated feedback stats for a user"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT feedback_type, COUNT(*) as count
                FROM user_feedback f
                JOIN user_profile p ON f.user_id = p.id
                WHERE p.user_id = %s
                GROUP BY feedback_type
                ORDER BY count DESC
            """, (user_id,))

            stats = {row["feedback_type"]: row["count"] for row in cur.fetchall()}
            return stats

    except Exception as e:
        log_with_context(logger, "error", "Failed to get feedback stats",
                        user_id=user_id, error=str(e))
        return {}


def get_coaching_context(user_id: int = None, telegram_id: int = None) -> Dict:
    """
    Get complete coaching context for a user.

    Returns dict with:
    - profile: User profile settings
    - adhd_contracts: Active ADHD output contracts
    - coaching_mode: Current coaching mode
    - recommendations: Based on feedback history
    """
    if user_id:
        profile = get_user_profile(user_id=user_id)
    elif telegram_id:
        profile = get_user_profile(telegram_id=telegram_id)
    else:
        profile = None

    if not profile:
        return {
            "profile": None,
            "adhd_contracts": [],
            "coaching_mode": "coach",
            "recommendations": []
        }

    # Build ADHD contracts if enabled
    adhd_contracts = []
    if profile.get("adhd_mode"):
        chunk_size = profile.get("chunk_size", "mittel")

        adhd_contracts = [
            "Max 3 Hauptpunkte pro Antwort",
            "Jede Antwort endet mit EINEM konkreten naechsten Schritt",
            "Keine langen Einleitungen",
            "TL;DR am Anfang bei laengeren Antworten"
        ]

        if chunk_size == "klein":
            adhd_contracts.append("Absaetze max 2 Zeilen")
        elif chunk_size == "mittel":
            adhd_contracts.append("Absaetze max 3 Zeilen")
        else:
            adhd_contracts.append("Absaetze max 5 Zeilen")

    # Get coaching mode
    coaching_mode = profile.get("active_coaching_mode", "coach")

    # Build recommendations from feedback
    recommendations = []
    if profile.get("user_id"):
        feedback_stats = get_user_feedback_stats(profile["user_id"])

        if feedback_stats.get("response_too_long", 0) > 3:
            recommendations.append("Nutzer bevorzugt kuerzere Antworten")
        if feedback_stats.get("response_too_short", 0) > 3:
            recommendations.append("Nutzer bevorzugt ausfuehrlichere Antworten")

    return {
        "profile": profile,
        "adhd_contracts": adhd_contracts,
        "coaching_mode": coaching_mode,
        "recommendations": recommendations
    }


# ============ Task Management Functions ============

def create_task(
    user_id: int,
    title: str,
    priority: str = "normal",
    due_date: str = None,
    context_tag: str = "jarvis"
) -> Optional[Dict]:
    """
    Create a new task.

    Args:
        user_id: User's ID (from user_profile)
        title: Short, actionable task title
        priority: low, normal, high
        due_date: Optional date string (YYYY-MM-DD)
        context_tag: jarvis, coding, projektil, admin, private

    Returns: Created task dict or None
    """
    if priority not in ("low", "normal", "high"):
        priority = "normal"

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO tasks (user_id, title, priority, due_date, context_tag)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (user_id, title, priority, due_date, context_tag))

            task = dict(cur.fetchone())
            log_with_context(logger, "info", "Task created",
                           task_id=task["id"], title=title[:30])
            return task

    except Exception as e:
        log_with_context(logger, "error", "Failed to create task", error=str(e))
        return None


def get_task(task_id: int) -> Optional[Dict]:
    """Get a single task by ID"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get task", task_id=task_id, error=str(e))
        return None


def get_tasks(
    user_id: int,
    status: str = None,
    priority: str = None,
    context_tag: str = None,
    due_before: str = None,
    include_done: bool = False,
    limit: int = 50
) -> List[Dict]:
    """
    Get tasks with filters.

    Args:
        user_id: User's ID
        status: Filter by status
        priority: Filter by priority
        context_tag: Filter by context
        due_before: Filter tasks due before date
        include_done: Include completed tasks
        limit: Max results

    Returns: List of task dicts
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            conditions = ["user_id = %s"]
            params = [user_id]

            if status:
                conditions.append("status = %s")
                params.append(status)
            elif not include_done:
                conditions.append("status != 'done'")

            if priority:
                conditions.append("priority = %s")
                params.append(priority)

            if context_tag:
                conditions.append("context_tag = %s")
                params.append(context_tag)

            if due_before:
                conditions.append("due_date <= %s")
                params.append(due_before)

            params.append(limit)

            cur.execute(f"""
                SELECT * FROM tasks
                WHERE {" AND ".join(conditions)}
                ORDER BY
                    CASE priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                    due_date NULLS LAST,
                    created_at DESC
                LIMIT %s
            """, params)

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get tasks", user_id=user_id, error=str(e))
        return []


def get_tasks_today(user_id: int) -> List[Dict]:
    """
    Get Today view: high priority + due today.
    Max 5 items (ADHD-protective).
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM tasks
                WHERE user_id = %s
                  AND status != 'done'
                  AND (priority = 'high' OR due_date <= CURRENT_DATE)
                ORDER BY
                    CASE priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                    due_date NULLS LAST
                LIMIT 5
            """, (user_id,))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get today tasks", error=str(e))
        return []


def get_tasks_week(user_id: int) -> List[Dict]:
    """Get tasks due in next 7 days."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM tasks
                WHERE user_id = %s
                  AND status != 'done'
                  AND due_date <= CURRENT_DATE + INTERVAL '7 days'
                ORDER BY
                    due_date NULLS LAST,
                    CASE priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END
                LIMIT 20
            """, (user_id,))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get week tasks", error=str(e))
        return []


def update_task(task_id: int, updates: Dict) -> bool:
    """
    Update a task.

    Allowed fields: title, status, priority, due_date, context_tag
    """
    ALLOWED_FIELDS = {"title", "status", "priority", "due_date", "context_tag"}
    valid_updates = {k: v for k, v in updates.items() if k in ALLOWED_FIELDS}

    if not valid_updates:
        return False

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            set_parts = [f"{k} = %s" for k in valid_updates.keys()]
            set_parts.append("updated_at = NOW()")
            params = list(valid_updates.values()) + [task_id]

            cur.execute(f"""
                UPDATE tasks
                SET {", ".join(set_parts)}
                WHERE id = %s
            """, params)

            log_with_context(logger, "info", "Task updated",
                           task_id=task_id, fields=list(valid_updates.keys()))
            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to update task",
                        task_id=task_id, error=str(e))
        return False


def update_task_status(task_id: int, status: str) -> bool:
    """Quick status update."""
    if status not in ("open", "in_progress", "blocked", "done"):
        return False
    return update_task(task_id, {"status": status})


def delete_task(task_id: int) -> bool:
    """Delete a task."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            log_with_context(logger, "info", "Task deleted", task_id=task_id)
            return cur.rowcount > 0

    except Exception as e:
        log_with_context(logger, "error", "Failed to delete task",
                        task_id=task_id, error=str(e))
        return False


def add_task_note(task_id: int, note: str, source_refs: Dict = None) -> Optional[int]:
    """Add a note to a task."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO task_notes (task_id, note, source_refs)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (task_id, note, json.dumps(source_refs) if source_refs else None))

            note_id = cur.fetchone()["id"]
            log_with_context(logger, "info", "Task note added",
                           task_id=task_id, note_id=note_id)
            return note_id

    except Exception as e:
        log_with_context(logger, "error", "Failed to add task note",
                        task_id=task_id, error=str(e))
        return None


def get_task_notes(task_id: int) -> List[Dict]:
    """Get all notes for a task."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM task_notes
                WHERE task_id = %s
                ORDER BY created_at DESC
            """, (task_id,))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get task notes",
                        task_id=task_id, error=str(e))
        return []


def get_task_stats(user_id: int) -> Dict:
    """Get task statistics for a user."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'open') as open,
                    COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                    COUNT(*) FILTER (WHERE status = 'blocked') as blocked,
                    COUNT(*) FILTER (WHERE status = 'done') as done,
                    COUNT(*) FILTER (WHERE priority = 'high' AND status != 'done') as high_priority,
                    COUNT(*) FILTER (WHERE due_date <= CURRENT_DATE AND status != 'done') as due_today
                FROM tasks
                WHERE user_id = %s
            """, (user_id,))

            row = cur.fetchone()
            return dict(row) if row else {}

    except Exception as e:
        log_with_context(logger, "error", "Failed to get task stats",
                        user_id=user_id, error=str(e))
        return {}


# ============ Salience Scoring Functions (Phase 11) ============

def add_salience_columns():
    """
    Migration: Add salience columns to existing knowledge_item table.
    Safe to run multiple times (uses IF NOT EXISTS pattern via ALTER TABLE).
    """
    migration_sql = """
    -- Add salience_score column
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'knowledge_item' AND column_name = 'salience_score') THEN
            ALTER TABLE knowledge_item ADD COLUMN salience_score FLOAT DEFAULT 0.5;
        END IF;
    END $$;

    -- Add decision_impact column
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'knowledge_item' AND column_name = 'decision_impact') THEN
            ALTER TABLE knowledge_item ADD COLUMN decision_impact FLOAT DEFAULT 0.0;
        END IF;
    END $$;

    -- Add goal_relevance column
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'knowledge_item' AND column_name = 'goal_relevance') THEN
            ALTER TABLE knowledge_item ADD COLUMN goal_relevance FLOAT DEFAULT 0.0;
        END IF;
    END $$;

    -- Add surprise_factor column
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'knowledge_item' AND column_name = 'surprise_factor') THEN
            ALTER TABLE knowledge_item ADD COLUMN surprise_factor FLOAT DEFAULT 0.0;
        END IF;
    END $$;

    -- Add salience_updated_at column
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'knowledge_item' AND column_name = 'salience_updated_at') THEN
            ALTER TABLE knowledge_item ADD COLUMN salience_updated_at TIMESTAMPTZ;
        END IF;
    END $$;

    -- Create index on salience_score if not exists
    CREATE INDEX IF NOT EXISTS idx_ki_salience ON knowledge_item(salience_score);
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(migration_sql)
        log_with_context(logger, "info", "Salience columns migration completed")
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to add salience columns", error=str(e))
        return False


def compute_salience_score(
    decision_impact: float = 0.0,
    goal_relevance: float = 0.0,
    surprise_factor: float = 0.0,
    relevance_score: float = 1.0
) -> float:
    """
    Compute overall salience score from components.

    Salience = weighted combination of:
    - 35% decision_impact: knowledge that led to good decisions
    - 30% goal_relevance: aligned with current goals/priorities
    - 20% surprise_factor: novel/unexpected information
    - 15% relevance_score: base relevance (recency/frequency)

    Returns: Float 0.0-1.0
    """
    WEIGHT_DECISION = 0.35
    WEIGHT_GOAL = 0.30
    WEIGHT_SURPRISE = 0.20
    WEIGHT_RELEVANCE = 0.15

    # Clamp inputs to 0.0-1.0
    di = max(0.0, min(1.0, decision_impact))
    gr = max(0.0, min(1.0, goal_relevance))
    sf = max(0.0, min(1.0, surprise_factor))
    rs = max(0.0, min(1.0, relevance_score))

    salience = (
        WEIGHT_DECISION * di +
        WEIGHT_GOAL * gr +
        WEIGHT_SURPRISE * sf +
        WEIGHT_RELEVANCE * rs
    )

    return round(salience, 4)


def update_knowledge_salience(
    item_id: int,
    decision_impact: float = None,
    goal_relevance: float = None,
    surprise_factor: float = None
) -> Optional[Dict]:
    """
    Update salience components and recompute salience_score for a knowledge item.

    Args:
        item_id: The knowledge item ID
        decision_impact: Positive outcome correlation (0-1), None to keep current
        goal_relevance: Relevance to active goals (0-1), None to keep current
        surprise_factor: Novelty/unexpectedness (0-1), None to keep current

    Returns: Updated item dict or None on error
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current values
            cur.execute("""
                SELECT id, relevance_score, decision_impact, goal_relevance, surprise_factor
                FROM knowledge_item WHERE id = %s
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                return None

            # Use provided values or keep existing
            di = decision_impact if decision_impact is not None else (row.get("decision_impact") or 0.0)
            gr = goal_relevance if goal_relevance is not None else (row.get("goal_relevance") or 0.0)
            sf = surprise_factor if surprise_factor is not None else (row.get("surprise_factor") or 0.0)
            rs = row.get("relevance_score") or 1.0

            # Compute new salience
            new_salience = compute_salience_score(di, gr, sf, rs)

            # Update
            cur.execute("""
                UPDATE knowledge_item
                SET decision_impact = %s,
                    goal_relevance = %s,
                    surprise_factor = %s,
                    salience_score = %s,
                    salience_updated_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
            """, (di, gr, sf, new_salience, item_id))

            updated = cur.fetchone()
            log_with_context(logger, "info", "Knowledge salience updated",
                           item_id=item_id, salience=new_salience)
            return dict(updated) if updated else None

    except Exception as e:
        log_with_context(logger, "error", "Failed to update salience",
                        item_id=item_id, error=str(e))
        return None


def reinforce_from_decision(
    item_id: int,
    outcome_rating: int,
    was_used: bool = True
) -> Optional[Dict]:
    """
    Reinforce salience based on decision outcome.

    Called when knowledge was used in a decision that had a measurable outcome.
    Positive outcomes increase decision_impact, negative outcomes decrease it.

    Args:
        item_id: The knowledge item ID
        outcome_rating: 1-10 rating of decision outcome
        was_used: Whether this knowledge was actually used in the decision

    Returns: Updated item dict or None on error
    """
    if not was_used:
        return None

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current decision_impact
            cur.execute("""
                SELECT decision_impact, relevance_score FROM knowledge_item WHERE id = %s
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                return None

            current_impact = row.get("decision_impact") or 0.0

            # Calculate impact adjustment
            # outcome_rating 1-10 maps to -0.1 to +0.1 adjustment
            # Good outcomes (7-10) increase, bad outcomes (1-4) decrease
            adjustment = (outcome_rating - 5) * 0.02  # -0.08 to +0.10

            # Apply adjustment with decay towards 0.5 (neutral)
            new_impact = current_impact + adjustment

            # Clamp to 0.0-1.0
            new_impact = max(0.0, min(1.0, new_impact))

            return update_knowledge_salience(item_id, decision_impact=new_impact)

    except Exception as e:
        log_with_context(logger, "error", "Failed to reinforce from decision",
                        item_id=item_id, error=str(e))
        return None


def set_goal_relevance(item_id: int, goal_id: str, relevance: float) -> Optional[Dict]:
    """
    Set goal relevance for a knowledge item.

    Args:
        item_id: The knowledge item ID
        goal_id: Identifier for the goal (for tracking)
        relevance: 0.0-1.0 how relevant this knowledge is to the goal

    Returns: Updated item dict or None on error
    """
    return update_knowledge_salience(item_id, goal_relevance=relevance)


def mark_as_surprising(item_id: int, surprise_level: float = 0.8) -> Optional[Dict]:
    """
    Mark a knowledge item as surprising/novel.

    Surprise decays over time (handled by batch process).

    Args:
        item_id: The knowledge item ID
        surprise_level: 0.0-1.0 how surprising (default 0.8)

    Returns: Updated item dict or None on error
    """
    return update_knowledge_salience(item_id, surprise_factor=surprise_level)


def decay_salience_batch(decay_rate: float = 0.05, min_salience: float = 0.1) -> Dict:
    """
    Apply time-based decay to salience components.

    Called periodically (e.g., daily) to gradually reduce:
    - goal_relevance: goals change over time
    - surprise_factor: novelty wears off

    decision_impact is NOT decayed (outcome-based learning should persist).

    Args:
        decay_rate: How much to decay (default 5%)
        min_salience: Minimum value to decay to (default 0.1)

    Returns: Dict with counts of updated items
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Decay goal_relevance and surprise_factor
            cur.execute("""
                UPDATE knowledge_item
                SET goal_relevance = GREATEST(%s, goal_relevance * (1 - %s)),
                    surprise_factor = GREATEST(%s, surprise_factor * (1 - %s)),
                    updated_at = NOW()
                WHERE status = 'active'
                AND (goal_relevance > %s OR surprise_factor > %s)
            """, (min_salience, decay_rate, min_salience, decay_rate, min_salience, min_salience))

            decayed_count = cur.rowcount

            # Recompute salience scores for affected items
            cur.execute("""
                UPDATE knowledge_item
                SET salience_score = (
                    0.35 * COALESCE(decision_impact, 0) +
                    0.30 * COALESCE(goal_relevance, 0) +
                    0.20 * COALESCE(surprise_factor, 0) +
                    0.15 * COALESCE(relevance_score, 1.0)
                ),
                salience_updated_at = NOW()
                WHERE status = 'active'
            """)

            log_with_context(logger, "info", "Salience decay batch completed",
                           decayed_count=decayed_count)

            return {
                "decayed_items": decayed_count,
                "decay_rate": decay_rate
            }

    except Exception as e:
        log_with_context(logger, "error", "Failed salience decay batch", error=str(e))
        return {"error": str(e)}


def get_high_salience_items(
    namespace: str = None,
    item_type: str = None,
    min_salience: float = 0.5,
    limit: int = 50
) -> List[Dict]:
    """
    Get knowledge items with high salience scores.

    Useful for:
    - Context injection (most relevant knowledge first)
    - Identifying important patterns
    - ADHD-friendly prioritization

    Args:
        namespace: Filter by namespace
        item_type: Filter by item type (pattern, fact, preference)
        min_salience: Minimum salience score (default 0.5)
        limit: Max items to return

    Returns: List of items ordered by salience DESC
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = """
                SELECT ki.*, kiv.content, kiv.confidence
                FROM knowledge_item ki
                LEFT JOIN knowledge_item_version kiv ON ki.current_version_id = kiv.id
                WHERE ki.status = 'active'
                AND COALESCE(ki.salience_score, 0) >= %s
            """
            params = [min_salience]

            if namespace:
                query += " AND ki.namespace = %s"
                params.append(namespace)

            if item_type:
                query += " AND ki.item_type = %s"
                params.append(item_type)

            query += " ORDER BY ki.salience_score DESC, ki.relevance_score DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get high salience items", error=str(e))
        return []


def get_salience_stats(namespace: str = None) -> Dict:
    """
    Get aggregate statistics about salience scores.

    Returns: Dict with salience distribution info
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            params = []
            namespace_filter = ""
            if namespace:
                namespace_filter = "AND namespace = %s"
                params.append(namespace)

            cur.execute(f"""
                SELECT
                    COUNT(*) as total_items,
                    AVG(salience_score) as avg_salience,
                    AVG(decision_impact) as avg_decision_impact,
                    AVG(goal_relevance) as avg_goal_relevance,
                    AVG(surprise_factor) as avg_surprise,
                    COUNT(*) FILTER (WHERE salience_score >= 0.7) as high_salience,
                    COUNT(*) FILTER (WHERE salience_score >= 0.4 AND salience_score < 0.7) as medium_salience,
                    COUNT(*) FILTER (WHERE salience_score < 0.4) as low_salience
                FROM knowledge_item
                WHERE status = 'active' {namespace_filter}
            """, params)

            row = cur.fetchone()
            if not row:
                return {}

            return {
                "total_items": row["total_items"],
                "avg_salience": round(float(row["avg_salience"] or 0), 3),
                "avg_decision_impact": round(float(row["avg_decision_impact"] or 0), 3),
                "avg_goal_relevance": round(float(row["avg_goal_relevance"] or 0), 3),
                "avg_surprise": round(float(row["avg_surprise"] or 0), 3),
                "distribution": {
                    "high": row["high_salience"],
                    "medium": row["medium_salience"],
                    "low": row["low_salience"]
                }
            }

    except Exception as e:
        log_with_context(logger, "error", "Failed to get salience stats", error=str(e))
        return {"error": str(e)}


# ============ Jarvis Personas ============

def get_all_personas(active_only: bool = True) -> List[Dict]:
    """Get all personas."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if active_only:
                cur.execute("SELECT * FROM jarvis_persona WHERE is_active = true ORDER BY name")
            else:
                cur.execute("SELECT * FROM jarvis_persona ORDER BY name")
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get personas", error=str(e))
        return []


def get_persona(persona_id: str) -> Optional[Dict]:
    """Get a single persona by ID."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jarvis_persona WHERE id = %s", (persona_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get persona", error=str(e))
        return None


def upsert_persona(
    persona_id: str,
    name: str,
    intent: str = None,
    tone: Dict = None,
    format_config: Dict = None,
    requirements: List[str] = None,
    forbidden: List[str] = None,
    example: str = None,
    is_default: bool = False
) -> Optional[Dict]:
    """Create or update a persona."""
    try:
        now = datetime.now()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jarvis_persona
                (id, name, intent, tone, format, requirements, forbidden, example, is_default, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    intent = EXCLUDED.intent,
                    tone = EXCLUDED.tone,
                    format = EXCLUDED.format,
                    requirements = EXCLUDED.requirements,
                    forbidden = EXCLUDED.forbidden,
                    example = EXCLUDED.example,
                    is_default = EXCLUDED.is_default,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
            """, (
                persona_id, name, intent,
                json.dumps(tone or {}),
                json.dumps(format_config or {}),
                json.dumps(requirements or []),
                json.dumps(forbidden or []),
                example, is_default, now, now
            ))
            result = cur.fetchone()
            log_with_context(logger, "info", "Persona upserted", persona_id=persona_id)
            return dict(result) if result else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to upsert persona", error=str(e))
        return None


def delete_persona(persona_id: str) -> bool:
    """Delete a persona."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM jarvis_persona WHERE id = %s", (persona_id,))
            deleted = cur.rowcount > 0
            if deleted:
                log_with_context(logger, "info", "Persona deleted", persona_id=persona_id)
            return deleted
    except Exception as e:
        log_with_context(logger, "error", "Failed to delete persona", error=str(e))
        return False


# ============ Jarvis Modes ============

def get_all_modes(active_only: bool = True) -> List[Dict]:
    """Get all modes."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if active_only:
                cur.execute("SELECT * FROM jarvis_mode WHERE is_active = true ORDER BY name")
            else:
                cur.execute("SELECT * FROM jarvis_mode ORDER BY name")
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get modes", error=str(e))
        return []


def get_mode(mode_id: str) -> Optional[Dict]:
    """Get a single mode by ID."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jarvis_mode WHERE id = %s", (mode_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get mode", error=str(e))
        return None


def upsert_mode(
    mode_id: str,
    name: str,
    purpose: str = None,
    output_contract: Dict = None,
    tone: Dict = None,
    forbidden: List[str] = None,
    citation_style: str = None,
    unknown_response: str = None,
    is_default: bool = False
) -> Optional[Dict]:
    """Create or update a mode."""
    try:
        now = datetime.now()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jarvis_mode
                (id, name, purpose, output_contract, tone, forbidden, citation_style, unknown_response, is_default, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    purpose = EXCLUDED.purpose,
                    output_contract = EXCLUDED.output_contract,
                    tone = EXCLUDED.tone,
                    forbidden = EXCLUDED.forbidden,
                    citation_style = EXCLUDED.citation_style,
                    unknown_response = EXCLUDED.unknown_response,
                    is_default = EXCLUDED.is_default,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
            """, (
                mode_id, name, purpose,
                json.dumps(output_contract or {}),
                json.dumps(tone or {}),
                json.dumps(forbidden or []),
                citation_style, unknown_response, is_default, now, now
            ))
            result = cur.fetchone()
            log_with_context(logger, "info", "Mode upserted", mode_id=mode_id)
            return dict(result) if result else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to upsert mode", error=str(e))
        return None


# ============ Jarvis Policies ============

def get_all_policies(category: str = None, active_only: bool = True) -> List[Dict]:
    """Get all policies, optionally filtered by category."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if category and active_only:
                cur.execute("""
                    SELECT * FROM jarvis_policy
                    WHERE category = %s AND is_active = true
                    ORDER BY priority DESC, name
                """, (category,))
            elif category:
                cur.execute("""
                    SELECT * FROM jarvis_policy
                    WHERE category = %s
                    ORDER BY priority DESC, name
                """, (category,))
            elif active_only:
                cur.execute("""
                    SELECT * FROM jarvis_policy
                    WHERE is_active = true
                    ORDER BY priority DESC, name
                """)
            else:
                cur.execute("SELECT * FROM jarvis_policy ORDER BY priority DESC, name")
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get policies", error=str(e))
        return []


def get_policy(policy_id: str) -> Optional[Dict]:
    """Get a single policy by ID."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jarvis_policy WHERE id = %s", (policy_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get policy", error=str(e))
        return None


def upsert_policy(
    policy_id: str,
    name: str,
    content: str,
    category: str = "general",
    priority: int = 100,
    inject_in_prompt: bool = True
) -> Optional[Dict]:
    """Create or update a policy."""
    try:
        now = datetime.now()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jarvis_policy
                (id, name, content, category, priority, inject_in_prompt, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    content = EXCLUDED.content,
                    category = EXCLUDED.category,
                    priority = EXCLUDED.priority,
                    inject_in_prompt = EXCLUDED.inject_in_prompt,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
            """, (
                policy_id, name, content, category, priority, inject_in_prompt, now, now
            ))
            result = cur.fetchone()
            log_with_context(logger, "info", "Policy upserted", policy_id=policy_id)
            return dict(result) if result else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to upsert policy", error=str(e))
        return None


def get_policies_for_prompt() -> str:
    """
    Get all active policies formatted for prompt injection.
    Returns policies ordered by priority (highest first).
    """
    policies = get_all_policies(active_only=True)
    if not policies:
        return ""

    prompt_policies = [p for p in policies if p.get("inject_in_prompt", True)]
    if not prompt_policies:
        return ""

    parts = []
    for p in prompt_policies:
        parts.append(f"## {p['name']}\n\n{p['content']}")

    return "\n\n---\n\n".join(parts)


# ============ Jarvis User Profile (Micha) ============

def get_jarvis_user_profile(profile_id: str = "micha") -> Optional[Dict]:
    """
    Get the user profile.
    This is much more comprehensive than external person profiles.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jarvis_user_profile WHERE id = %s", (profile_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get user profile", error=str(e))
        return None


def ensure_user_profile(profile_id: str = "micha", display_name: str = "Micha") -> Dict:
    """
    Ensure user profile exists, create with defaults if not.
    """
    profile = get_jarvis_user_profile(profile_id)
    if profile:
        return profile

    try:
        now = datetime.now()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jarvis_user_profile (id, display_name, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING *
            """, (profile_id, display_name, now, now))
            result = cur.fetchone()
            if result:
                log_with_context(logger, "info", "User profile created", profile_id=profile_id)
                return dict(result)
            return get_jarvis_user_profile(profile_id)
    except Exception as e:
        log_with_context(logger, "error", "Failed to create user profile", error=str(e))
        return {}


def update_user_profile(
    profile_id: str = "micha",
    display_name: str = None,
    roles: List[str] = None,
    communication_prefs: Dict = None,
    work_prefs: Dict = None,
    current_goals: List[Dict] = None,
    long_term_goals: List[Dict] = None,
    anti_goals: List[str] = None,
    adhd_patterns: Dict = None,
    boundaries: Dict = None,
    vip_contacts: List[str] = None,
    what_works: List[str] = None,
    what_fails: List[str] = None
) -> Optional[Dict]:
    """
    Update specific fields of the user profile.
    Only updates fields that are provided (not None).
    For JSONB fields, merges with existing data.
    """
    try:
        now = datetime.now()
        ensure_user_profile(profile_id)

        with get_conn() as conn:
            cur = conn.cursor()

            # Get current profile for merging
            cur.execute("SELECT * FROM jarvis_user_profile WHERE id = %s", (profile_id,))
            current = dict(cur.fetchone())

            updates = ["updated_at = %s"]
            params = [now]

            if display_name is not None:
                updates.append("display_name = %s")
                params.append(display_name)

            if roles is not None:
                updates.append("roles = %s")
                params.append(json.dumps(roles))

            if communication_prefs is not None:
                merged = {**current.get("communication_prefs", {}), **communication_prefs}
                updates.append("communication_prefs = %s")
                params.append(json.dumps(merged))

            if work_prefs is not None:
                merged = {**current.get("work_prefs", {}), **work_prefs}
                updates.append("work_prefs = %s")
                params.append(json.dumps(merged))

            if current_goals is not None:
                updates.append("current_goals = %s")
                params.append(json.dumps(current_goals))

            if long_term_goals is not None:
                updates.append("long_term_goals = %s")
                params.append(json.dumps(long_term_goals))

            if anti_goals is not None:
                existing = set(current.get("anti_goals", []))
                merged = list(existing | set(anti_goals))
                updates.append("anti_goals = %s")
                params.append(json.dumps(merged))

            if adhd_patterns is not None:
                merged = {**current.get("adhd_patterns", {}), **adhd_patterns}
                updates.append("adhd_patterns = %s")
                params.append(json.dumps(merged))

            if boundaries is not None:
                merged = {**current.get("boundaries", {}), **boundaries}
                updates.append("boundaries = %s")
                params.append(json.dumps(merged))

            if vip_contacts is not None:
                existing = set(current.get("vip_contacts", []))
                merged = list(existing | set(vip_contacts))
                updates.append("vip_contacts = %s")
                params.append(json.dumps(merged))

            if what_works is not None:
                existing = set(current.get("what_works", []))
                merged = list(existing | set(what_works))
                updates.append("what_works = %s")
                params.append(json.dumps(merged))

            if what_fails is not None:
                existing = set(current.get("what_fails", []))
                merged = list(existing | set(what_fails))
                updates.append("what_fails = %s")
                params.append(json.dumps(merged))

            params.append(profile_id)

            cur.execute(f"""
                UPDATE jarvis_user_profile
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING *
            """, params)

            result = cur.fetchone()
            log_with_context(logger, "info", "User profile updated", profile_id=profile_id)
            return dict(result) if result else None

    except Exception as e:
        log_with_context(logger, "error", "Failed to update user profile", error=str(e))
        return None


def add_user_goal(
    title: str,
    priority: int = 3,
    deadline: str = None,
    namespace: str = None,
    goal_type: str = "current",  # "current" or "long_term"
    profile_id: str = "micha"
) -> Dict:
    """Add a goal to the user profile."""
    import uuid
    goal = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "priority": priority,
        "deadline": deadline,
        "namespace": namespace,
        "created_at": datetime.now().isoformat()
    }

    profile = get_jarvis_user_profile(profile_id) or ensure_user_profile(profile_id)

    if goal_type == "long_term":
        goals = profile.get("long_term_goals", [])
    else:
        goals = profile.get("current_goals", [])

    goals.append(goal)

    if goal_type == "long_term":
        update_user_profile(profile_id, long_term_goals=goals)
    else:
        update_user_profile(profile_id, current_goals=goals)

    return goal


def complete_user_goal(goal_id: str, profile_id: str = "micha") -> bool:
    """Mark a goal as completed and move to milestones."""
    profile = get_jarvis_user_profile(profile_id)
    if not profile:
        return False

    current_goals = profile.get("current_goals", [])
    completed_goal = None

    for i, g in enumerate(current_goals):
        if g.get("id") == goal_id:
            completed_goal = current_goals.pop(i)
            break

    if not completed_goal:
        return False

    completed_goal["completed_at"] = datetime.now().isoformat()
    milestones = profile.get("milestones", [])
    milestones.append({
        "type": "goal_completed",
        "goal": completed_goal,
        "date": datetime.now().isoformat()
    })

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE jarvis_user_profile
                SET current_goals = %s, milestones = %s, updated_at = %s
                WHERE id = %s
            """, (json.dumps(current_goals), json.dumps(milestones), datetime.now(), profile_id))
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to complete goal", error=str(e))
        return False


def get_user_profile_for_prompt(profile_id: str = "micha") -> str:
    """
    Get user profile formatted for prompt injection.
    Returns a concise summary suitable for system prompt context.
    """
    profile = get_jarvis_user_profile(profile_id)
    if not profile:
        return ""

    parts = ["## Ueber den User"]

    # Communication style
    comm = profile.get("communication_prefs", {})
    if comm:
        style_parts = []
        if comm.get("style"):
            style_parts.append(comm["style"])
        if comm.get("format"):
            style_parts.append(comm["format"])
        if style_parts:
            parts.append(f"**Kommunikation:** {', '.join(style_parts)}")

    # Work preferences
    work = profile.get("work_prefs", {})
    if work.get("max_parallel_threads"):
        parts.append(f"**Max parallele Threads:** {work['max_parallel_threads']}")

    # Current goals (top 3)
    goals = profile.get("current_goals", [])
    if goals:
        sorted_goals = sorted(goals, key=lambda g: g.get("priority", 0), reverse=True)[:3]
        goal_strs = [f"- {g['title']} (Prio {g.get('priority', 3)})" for g in sorted_goals]
        parts.append("**Aktuelle Ziele:**\n" + "\n".join(goal_strs))

    # ADHD patterns
    adhd = profile.get("adhd_patterns", {})
    if adhd.get("known_loops"):
        parts.append(f"**Bekannte Loops:** {', '.join(adhd['known_loops'][:3])}")
    if adhd.get("coping_strategies"):
        parts.append(f"**Coping:** {', '.join(adhd['coping_strategies'][:3])}")

    # What works/fails
    works = profile.get("what_works", [])
    fails = profile.get("what_fails", [])
    if works:
        parts.append(f"**Was funktioniert:** {', '.join(works[:3])}")
    if fails:
        parts.append(f"**Was vermeiden:** {', '.join(fails[:3])}")

    # Boundaries
    boundaries = profile.get("boundaries", {})
    if boundaries.get("jarvis_should_never"):
        parts.append(f"**Jarvis soll nie:** {', '.join(boundaries['jarvis_should_never'])}")

    return "\n".join(parts)


def create_user_profile_snapshot(profile_id: str = "micha", reason: str = "manual") -> Optional[int]:
    """Create a snapshot of the current user profile."""
    profile = get_jarvis_user_profile(profile_id)
    if not profile:
        return None

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jarvis_user_profile_snapshot
                (profile_id, snapshot_reason, goals_snapshot, patterns_snapshot, learnings_snapshot)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                profile_id, reason,
                json.dumps(profile.get("current_goals", [])),
                json.dumps(profile.get("adhd_patterns", {})),
                json.dumps({
                    "what_works": profile.get("what_works", []),
                    "what_fails": profile.get("what_fails", [])
                })
            ))
            result = cur.fetchone()
            return result["id"] if result else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to create user profile snapshot", error=str(e))
        return None


# ============ Jarvis Self-Model (Personality Consolidation) ============

def get_self_model(model_id: str = "default") -> Optional[Dict]:
    """
    Get Jarvis' current self-model.
    
    The self-model contains:
    - Strengths/weaknesses observed across sessions
    - User patterns and preferences learned
    - Current self-perception and confidence
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jarvis_self_model WHERE id = %s", (model_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get self-model", error=str(e))
        return None


def update_self_model(
    model_id: str = "default",
    strengths: List[str] = None,
    weaknesses: List[str] = None,
    wishes: List[str] = None,
    user_patterns: Dict = None,
    user_preferences: Dict = None,
    current_feeling: str = None,
    confidence_level: float = None
) -> Optional[Dict]:
    """
    Update Jarvis' self-model.
    
    Uses JSONB merge for list/dict fields - new items are appended, not replaced.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            now = datetime.now()
            
            # Ensure model exists
            cur.execute("""
                INSERT INTO jarvis_self_model (id, created_at, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (model_id, now, now))
            
            # Build update
            updates = ["updated_at = %s"]
            params = [now]
            
            if strengths is not None:
                # Merge new strengths with existing (unique)
                updates.append("strengths = (SELECT jsonb_agg(DISTINCT value) FROM jsonb_array_elements(COALESCE(strengths, '[]'::jsonb) || %s::jsonb))")
                params.append(json.dumps(strengths))
            
            if weaknesses is not None:
                updates.append("weaknesses = (SELECT jsonb_agg(DISTINCT value) FROM jsonb_array_elements(COALESCE(weaknesses, '[]'::jsonb) || %s::jsonb))")
                params.append(json.dumps(weaknesses))
            
            if wishes is not None:
                updates.append("wishes = (SELECT jsonb_agg(DISTINCT value) FROM jsonb_array_elements(COALESCE(wishes, '[]'::jsonb) || %s::jsonb))")
                params.append(json.dumps(wishes))
            
            if user_patterns is not None:
                updates.append("user_patterns = COALESCE(user_patterns, '{}'::jsonb) || %s::jsonb")
                params.append(json.dumps(user_patterns))
            
            if user_preferences is not None:
                updates.append("user_preferences = COALESCE(user_preferences, '{}'::jsonb) || %s::jsonb")
                params.append(json.dumps(user_preferences))
            
            if current_feeling is not None:
                updates.append("current_feeling = %s")
                params.append(current_feeling)
            
            if confidence_level is not None:
                updates.append("confidence_level = %s")
                params.append(confidence_level)
            
            params.append(model_id)
            
            cur.execute(f"""
                UPDATE jarvis_self_model
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING *
            """, params)
            
            result = cur.fetchone()
            log_with_context(logger, "info", "Self-model updated", model_id=model_id)
            return dict(result) if result else None
            
    except Exception as e:
        log_with_context(logger, "error", "Failed to update self-model", error=str(e))
        return None


def create_self_model_snapshot(
    model_id: str = "default",
    reason: str = "manual"
) -> Optional[int]:
    """
    Create a snapshot of the current self-model for history tracking.
    
    Reasons: "weekly", "significant_learning", "user_feedback", "manual"
    """
    try:
        model = get_self_model(model_id)
        if not model:
            return None
        
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jarvis_self_model_snapshot
                (model_id, snapshot_reason, strengths, weaknesses, wishes,
                 user_patterns, current_feeling, confidence_level)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                model_id, reason,
                json.dumps(model.get("strengths", [])),
                json.dumps(model.get("weaknesses", [])),
                json.dumps(model.get("wishes", [])),
                json.dumps(model.get("user_patterns", {})),
                model.get("current_feeling"),
                model.get("confidence_level")
            ))
            
            snapshot_id = cur.fetchone()["id"]
            log_with_context(logger, "info", "Self-model snapshot created",
                           model_id=model_id, snapshot_id=snapshot_id, reason=reason)
            return snapshot_id
            
    except Exception as e:
        log_with_context(logger, "error", "Failed to create snapshot", error=str(e))
        return None


def consolidate_self_model(model_id: str = "default") -> Dict:
    """
    Run consolidation job to update self-model from recent interactions.
    
    Analyzes:
    - Recent conversations for patterns
    - Feedback signals (positive/negative)
    - Self-reflection markers
    
    Returns summary of what was consolidated.
    """
    try:
        from . import postgres_state as pg
        
        consolidated = {
            "new_learnings": [],
            "updated_fields": [],
            "snapshot_created": False
        }
        
        with get_conn() as conn:
            cur = conn.cursor()
            now = datetime.now()
            
            # Get recent messages (last 7 days) for analysis
            cur.execute("""
                SELECT m.role, m.content, m.created_at, c.namespace
                FROM message m
                JOIN conversation c ON m.session_id = c.session_id
                WHERE m.created_at > NOW() - INTERVAL '7 days'
                ORDER BY m.created_at DESC
                LIMIT 200
            """)
            messages = [dict(row) for row in cur.fetchall()]
            
            if not messages:
                return {"status": "no_data", "message": "No recent messages to analyze"}
            
            # Analyze patterns in user messages
            user_messages = [m for m in messages if m["role"] == "user"]
            assistant_messages = [m for m in messages if m["role"] == "assistant"]
            
            # Detect recurring themes in user messages
            patterns_found = _analyze_user_patterns(user_messages)
            if patterns_found:
                update_self_model(model_id, user_patterns=patterns_found)
                consolidated["new_learnings"].append(f"User patterns: {list(patterns_found.keys())}")
                consolidated["updated_fields"].append("user_patterns")
            
            # Analyze assistant performance indicators
            performance = _analyze_assistant_performance(assistant_messages, user_messages)
            if performance.get("strengths"):
                update_self_model(model_id, strengths=performance["strengths"])
                consolidated["updated_fields"].append("strengths")
            if performance.get("weaknesses"):
                update_self_model(model_id, weaknesses=performance["weaknesses"])
                consolidated["updated_fields"].append("weaknesses")
            
            # Update session stats
            cur.execute("""
                UPDATE jarvis_self_model
                SET total_sessions = (SELECT COUNT(DISTINCT session_id) FROM conversation),
                    last_consolidation = %s,
                    updated_at = %s
                WHERE id = %s
            """, (now, now, model_id))
            
            # Create snapshot if significant changes
            if len(consolidated["updated_fields"]) >= 2:
                snapshot_id = create_self_model_snapshot(model_id, "consolidation")
                consolidated["snapshot_created"] = snapshot_id is not None
            
            consolidated["status"] = "success"
            consolidated["messages_analyzed"] = len(messages)
            
            log_with_context(logger, "info", "Self-model consolidation complete",
                           model_id=model_id, learnings=len(consolidated["new_learnings"]))
            
            return consolidated
            
    except Exception as e:
        log_with_context(logger, "error", "Consolidation failed", error=str(e))
        return {"status": "error", "error": str(e)}


def _analyze_user_patterns(messages: List[Dict]) -> Dict:
    """Analyze user messages for recurring patterns."""
    patterns = {}
    
    # Simple keyword-based pattern detection
    text = " ".join([m.get("content", "") for m in messages]).lower()
    
    # Check for system thinking
    if text.count("system") > 3 or text.count("architektur") > 2:
        patterns["thinks_in_systems"] = True
    
    # Check for ADHD-related patterns
    if text.count("overwhelm") > 1 or text.count("fokus") > 2:
        patterns["adhd_aware"] = True
    
    # Check for bullet preference
    bullet_count = text.count("•") + text.count("-")
    if bullet_count > 10:
        patterns["prefers_bullets"] = True
    
    # Check for refinement over revolution
    if text.count("85%") > 0 or (text.count("refine") > 0 and text.count("revolution") == 0):
        patterns["refinement_over_revolution"] = True
    
    return patterns


def _analyze_assistant_performance(assistant_msgs: List[Dict], user_msgs: List[Dict]) -> Dict:
    """Analyze assistant messages for performance indicators."""
    result = {"strengths": [], "weaknesses": []}
    
    # Check for coaching indicators
    coaching_keywords = ["containment", "scope reduz", "ein schritt", "atem"]
    coaching_count = sum(1 for m in assistant_msgs 
                        if any(kw in m.get("content", "").lower() for kw in coaching_keywords))
    if coaching_count >= 2:
        result["strengths"].append("Coaching bei Overwhelm funktioniert gut")
    
    # Check for loop indicators (repeated similar content)
    # This is a simple heuristic
    contents = [m.get("content", "")[:100] for m in assistant_msgs]
    if len(contents) != len(set(contents)):
        result["weaknesses"].append("Gelegentliche Wiederholungs-Loops")
    
    # Check for positive feedback in user messages
    positive_words = ["danke", "perfekt", "gut", "super", "genau"]
    positive_count = sum(1 for m in user_msgs 
                        if any(w in m.get("content", "").lower() for w in positive_words))
    if positive_count >= 3:
        result["strengths"].append("Positive Rueckmeldungen haeufig")
    
    # Check for frustration in user messages
    frustration_words = ["nein", "falsch", "nicht", "wieder"]
    frustration_count = sum(1 for m in user_msgs 
                          if any(w in m.get("content", "").lower() for w in frustration_words))
    if frustration_count >= 5:
        result["weaknesses"].append("Manchmal Missverstaendnisse")
    
    return result


def get_self_model_for_prompt(model_id: str = "default") -> str:
    """
    Get self-model formatted for injection into system prompt.
    
    Returns a concise summary suitable for context injection.
    """
    model = get_self_model(model_id)
    if not model:
        return ""
    
    parts = ["## Meine aktuelle Selbstwahrnehmung (aus Consolidation)"]
    
    if model.get("current_feeling"):
        parts.append(f"\n**Aktuelles Gefuehl:** {model['current_feeling']}")
    
    strengths = model.get("strengths", [])
    if strengths:
        parts.append(f"\n**Was gut laeuft:** {', '.join(strengths[:3])}")
    
    weaknesses = model.get("weaknesses", [])
    if weaknesses:
        parts.append(f"\n**Wo es hakt:** {', '.join(weaknesses[:3])}")
    
    wishes = model.get("wishes", [])
    if wishes:
        parts.append(f"\n**Meine Wuensche:** {', '.join(wishes[:3])}")
    
    user_patterns = model.get("user_patterns", {})
    if user_patterns:
        pattern_list = [k for k, v in user_patterns.items() if v]
        if pattern_list:
            parts.append(f"\n**User-Patterns erkannt:** {', '.join(pattern_list[:3])}")

    return "\n".join(parts)


# ============ Upload Queue Functions ============

def create_upload_entry(
    filename: str,
    file_path: str,
    source_type: str,
    namespace: str,
    channel_hint: str = None,
    file_size_bytes: int = None,
    file_hash: str = None,
    priority: int = 3,
    uploaded_by: str = "api",
    metadata: Dict = None
) -> Dict:
    """
    Create a new entry in the upload queue.

    Returns the created entry with its UUID.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO upload_queue
                (filename, file_path, source_type, namespace, channel_hint,
                 file_size_bytes, file_hash, priority, uploaded_by, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                filename, file_path, source_type, namespace, channel_hint,
                file_size_bytes, file_hash, priority, uploaded_by,
                json.dumps(metadata or {})
            ))
            row = cur.fetchone()
            log_with_context(logger, "info", "Upload queue entry created",
                           filename=filename, source_type=source_type)
            return dict(row)
    except Exception as e:
        log_with_context(logger, "error", "Failed to create upload entry", error=str(e))
        return {"error": str(e)}


def get_upload_entry(upload_id: str) -> Optional[Dict]:
    """Get a specific upload entry by ID."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM upload_queue WHERE id = %s", (upload_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get upload entry", error=str(e))
        return None


def get_upload_queue(
    status: str = None,
    namespace: str = None,
    source_type: str = None,
    limit: int = 50
) -> List[Dict]:
    """
    Get upload queue entries with optional filters.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            conditions = []
            params = []

            if status:
                conditions.append("status = %s")
                params.append(status)
            if namespace:
                conditions.append("namespace = %s")
                params.append(namespace)
            if source_type:
                conditions.append("source_type = %s")
                params.append(source_type)

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)

            cur.execute(f"""
                SELECT * FROM upload_queue
                WHERE {where_clause}
                ORDER BY priority DESC, uploaded_at DESC
                LIMIT %s
            """, params)

            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get upload queue", error=str(e))
        return []


def claim_next_pending_upload(namespace: str = None, source_type: str = None) -> Optional[Dict]:
    """
    Atomically claim the next pending upload for processing.
    Uses SELECT FOR UPDATE SKIP LOCKED to handle concurrent workers.

    Returns the claimed upload entry or None if no pending uploads.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            where_parts = ["status = 'pending'"]
            params = []

            if namespace:
                where_parts.append("namespace = %s")
                params.append(namespace)

            if source_type:
                where_parts.append("source_type = %s")
                params.append(source_type)

            where_clause = " AND ".join(where_parts)

            # Claim the highest priority, oldest pending upload
            cur.execute(f"""
                UPDATE upload_queue
                SET status = 'processing', processing_started_at = NOW()
                WHERE id = (
                    SELECT id FROM upload_queue
                    WHERE {where_clause}
                    ORDER BY priority DESC, uploaded_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """, params)

            row = cur.fetchone()
            if row:
                log_with_context(logger, "info", "Claimed upload for processing",
                               upload_id=str(row["id"]), filename=row["filename"])
                return dict(row)
            return None

    except Exception as e:
        log_with_context(logger, "error", "Failed to claim upload", error=str(e))
        return None


def retry_failed_uploads(max_age_hours: int = 24, limit: int = 10) -> Dict:
    """
    Reset old failed uploads back to pending for retry.

    Args:
        max_age_hours: Only retry uploads that failed within this time
        limit: Maximum number to reset

    Returns:
        Dict with count of retried uploads
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                UPDATE upload_queue
                SET status = 'pending', error_message = NULL, processing_log = '[]'
                WHERE status = 'failed'
                  AND completed_at > NOW() - INTERVAL '%s hours'
                  AND id IN (
                    SELECT id FROM upload_queue
                    WHERE status = 'failed'
                      AND completed_at > NOW() - INTERVAL '%s hours'
                    LIMIT %s
                  )
            """, (max_age_hours, max_age_hours, limit))

            retried = cur.rowcount
            log_with_context(logger, "info", "Retried failed uploads", count=retried)
            return {"retried": retried}

    except Exception as e:
        log_with_context(logger, "error", "Failed to retry uploads", error=str(e))
        return {"error": str(e)}


def update_upload_status(
    upload_id: str,
    status: str,
    error_message: str = None,
    messages_extracted: int = None,
    profiles_updated: List[str] = None,
    knowledge_items_created: int = None,
    processing_log: List[Dict] = None
) -> Optional[Dict]:
    """
    Update upload entry status and results.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            now = datetime.now()

            updates = ["status = %s"]
            params = [status]

            if status == "processing":
                updates.append("processing_started_at = %s")
                params.append(now)
            elif status in ("done", "failed"):
                updates.append("completed_at = %s")
                params.append(now)
            elif status == "archived":
                updates.append("archived_at = %s")
                params.append(now)

            if error_message is not None:
                updates.append("error_message = %s")
                params.append(error_message)

            if messages_extracted is not None:
                updates.append("messages_extracted = %s")
                params.append(messages_extracted)

            if profiles_updated is not None:
                updates.append("profiles_updated = %s")
                params.append(profiles_updated)

            if knowledge_items_created is not None:
                updates.append("knowledge_items_created = %s")
                params.append(knowledge_items_created)

            if processing_log is not None:
                updates.append("processing_log = %s")
                params.append(json.dumps(processing_log))

            params.append(upload_id)

            cur.execute(f"""
                UPDATE upload_queue
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING *
            """, params)

            row = cur.fetchone()
            log_with_context(logger, "info", "Upload status updated",
                           upload_id=upload_id, status=status)
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to update upload status", error=str(e))
        return None


def check_duplicate_upload(file_hash: str) -> Optional[Dict]:
    """
    Check if a file with this hash was already uploaded.
    Returns the existing entry if found.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM upload_queue
                WHERE file_hash = %s AND status IN ('done', 'processing')
                ORDER BY uploaded_at DESC
                LIMIT 1
            """, (file_hash,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to check duplicate", error=str(e))
        return None


def archive_old_uploads(
    days_old: int = 30,
    status: str = "done",
    namespace: str = None,
    limit: int = 100
) -> Dict:
    """
    Archive old uploads that have been successfully processed.

    Args:
        days_old: Archive uploads older than this many days
        status: Only archive uploads with this status (default: 'done')
        namespace: Optional filter by namespace
        limit: Maximum number to archive in one call

    Returns:
        Dict with count of archived uploads
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = """
                UPDATE upload_queue
                SET status = 'archived', archived_at = NOW()
                WHERE status = %s
                  AND uploaded_at < NOW() - INTERVAL '%s days'
            """
            params = [status, days_old]

            if namespace:
                query += " AND namespace = %s"
                params.append(namespace)

            query += " AND id IN (SELECT id FROM upload_queue WHERE status = %s"
            params.append(status)

            if namespace:
                query += " AND namespace = %s"
                params.append(namespace)

            query += f" AND uploaded_at < NOW() - INTERVAL '{days_old} days' LIMIT {limit})"

            cur.execute(query, params)
            archived_count = cur.rowcount

            log_with_context(logger, "info", "Archived old uploads",
                           count=archived_count, days_old=days_old, namespace=namespace)

            return {"archived": archived_count, "days_old": days_old}

    except Exception as e:
        log_with_context(logger, "error", "Failed to archive uploads", error=str(e))
        return {"error": str(e)}


def cleanup_archived_uploads(
    days_archived: int = 7,
    delete_files: bool = False,
    namespace: str = None,
    limit: int = 50
) -> Dict:
    """
    Permanently delete archived uploads from database.
    Optionally delete the source files as well.

    Args:
        days_archived: Delete uploads archived more than this many days ago
        delete_files: If True, also delete the source files
        namespace: Optional filter by namespace
        limit: Maximum number to delete in one call

    Returns:
        Dict with count of deleted uploads and files
    """
    import os

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # First, get the uploads to delete (for file cleanup)
            query = """
                SELECT id, file_path FROM upload_queue
                WHERE status = 'archived'
                  AND archived_at < NOW() - INTERVAL '%s days'
            """
            params = [days_archived]

            if namespace:
                query += " AND namespace = %s"
                params.append(namespace)

            query += f" LIMIT {limit}"

            cur.execute(query, params)
            uploads_to_delete = cur.fetchall()

            if not uploads_to_delete:
                return {"deleted": 0, "files_deleted": 0}

            # Delete files if requested
            files_deleted = 0
            file_errors = []
            if delete_files:
                for upload in uploads_to_delete:
                    file_path = upload.get("file_path")
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            files_deleted += 1
                        except Exception as e:
                            file_errors.append({"path": file_path, "error": str(e)})

            # Delete from database
            upload_ids = [u["id"] for u in uploads_to_delete]
            cur.execute(
                "DELETE FROM upload_queue WHERE id = ANY(%s)",
                (upload_ids,)
            )
            deleted_count = cur.rowcount

            log_with_context(logger, "info", "Cleaned up archived uploads",
                           deleted=deleted_count, files_deleted=files_deleted,
                           days_archived=days_archived)

            result = {
                "deleted": deleted_count,
                "files_deleted": files_deleted
            }
            if file_errors:
                result["file_errors"] = file_errors

            return result

    except Exception as e:
        log_with_context(logger, "error", "Failed to cleanup uploads", error=str(e))
        return {"error": str(e)}


def get_upload_stats() -> Dict:
    """Get statistics about upload queue."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Count by status
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM upload_queue
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cur.fetchall()}

            # Count by namespace
            cur.execute("""
                SELECT namespace, COUNT(*) as count
                FROM upload_queue
                WHERE status != 'archived'
                GROUP BY namespace
            """)
            namespace_counts = {row["namespace"]: row["count"] for row in cur.fetchall()}

            # Oldest pending/failed
            cur.execute("""
                SELECT status, MIN(uploaded_at) as oldest
                FROM upload_queue
                WHERE status IN ('pending', 'failed')
                GROUP BY status
            """)
            oldest = {row["status"]: row["oldest"].isoformat() if row["oldest"] else None
                     for row in cur.fetchall()}

            # Total messages processed
            cur.execute("""
                SELECT SUM(messages_extracted) as total
                FROM upload_queue
                WHERE status = 'done'
            """)
            row = cur.fetchone()
            total_messages = row["total"] if row and row["total"] else 0

            return {
                "by_status": status_counts,
                "by_namespace": namespace_counts,
                "oldest_pending_failed": oldest,
                "total_messages_processed": total_messages
            }

    except Exception as e:
        log_with_context(logger, "error", "Failed to get upload stats", error=str(e))
        return {"error": str(e)}


# ============ Chat Sync State Functions ============

def get_sync_state(source_type: str, namespace: str, channel_id: str = None) -> Optional[Dict]:
    """Get sync state for a channel."""
    try:
        sync_id = f"{source_type}:{namespace}:{channel_id or 'default'}"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM chat_sync_state WHERE id = %s", (sync_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get sync state", error=str(e))
        return None


def update_sync_state(
    source_type: str,
    namespace: str,
    channel_id: str = None,
    channel_name: str = None,
    last_message_ts: datetime = None,
    last_message_id: str = None,
    messages_processed: int = 0,
    participants: List[str] = None
) -> Dict:
    """
    Update or create sync state for a channel.
    """
    try:
        sync_id = f"{source_type}:{namespace}:{channel_id or 'default'}"
        now = datetime.now()

        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO chat_sync_state
                (id, source_type, namespace, channel_id, channel_name,
                 last_message_ts, last_message_id, total_messages_processed,
                 unique_participants, first_sync, last_sync)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    channel_name = COALESCE(EXCLUDED.channel_name, chat_sync_state.channel_name),
                    last_message_ts = COALESCE(EXCLUDED.last_message_ts, chat_sync_state.last_message_ts),
                    last_message_id = COALESCE(EXCLUDED.last_message_id, chat_sync_state.last_message_id),
                    total_messages_processed = chat_sync_state.total_messages_processed + EXCLUDED.total_messages_processed,
                    unique_participants = (
                        SELECT array_agg(DISTINCT elem)
                        FROM unnest(
                            COALESCE(chat_sync_state.unique_participants, ARRAY[]::text[]) ||
                            COALESCE(EXCLUDED.unique_participants, ARRAY[]::text[])
                        ) as elem
                    ),
                    last_sync = EXCLUDED.last_sync
                RETURNING *
            """, (
                sync_id, source_type, namespace, channel_id, channel_name,
                last_message_ts, last_message_id, messages_processed,
                participants or [], now, now
            ))

            row = cur.fetchone()
            log_with_context(logger, "info", "Sync state updated",
                           sync_id=sync_id, messages=messages_processed)
            return dict(row) if row else {}
    except Exception as e:
        log_with_context(logger, "error", "Failed to update sync state", error=str(e))
        return {"error": str(e)}


def get_all_sync_states(namespace: str = None) -> List[Dict]:
    """Get all sync states, optionally filtered by namespace."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if namespace:
                cur.execute("""
                    SELECT * FROM chat_sync_state
                    WHERE namespace = %s
                    ORDER BY last_sync DESC
                """, (namespace,))
            else:
                cur.execute("SELECT * FROM chat_sync_state ORDER BY last_sync DESC")
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get sync states", error=str(e))
        return []


# ============ Person Relationship Functions ============

def upsert_relationship(
    person_a_id: str,
    person_b_id: str,
    relationship_type: str,
    namespace: str,
    strength: int = 3,
    sentiment: str = "neutral",
    notes: str = None,
    evidence_refs: List[str] = None,
    confidence: float = 0.5
) -> Dict:
    """
    Create or update a relationship between two persons.
    """
    try:
        now = datetime.now()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO person_relationship
                (person_a_id, person_b_id, relationship_type, namespace,
                 strength, sentiment, notes, evidence_refs, confidence,
                 first_observed, last_observed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (person_a_id, person_b_id, relationship_type, namespace)
                DO UPDATE SET
                    strength = EXCLUDED.strength,
                    sentiment = EXCLUDED.sentiment,
                    notes = COALESCE(EXCLUDED.notes, person_relationship.notes),
                    evidence_refs = person_relationship.evidence_refs || EXCLUDED.evidence_refs,
                    confidence = GREATEST(person_relationship.confidence, EXCLUDED.confidence),
                    last_observed = EXCLUDED.last_observed,
                    updated_at = NOW()
                RETURNING *
            """, (
                person_a_id, person_b_id, relationship_type, namespace,
                strength, sentiment, notes, json.dumps(evidence_refs or []),
                confidence, now, now
            ))
            row = cur.fetchone()
            return dict(row) if row else {}
    except Exception as e:
        log_with_context(logger, "error", "Failed to upsert relationship", error=str(e))
        return {"error": str(e)}


def get_person_relationships(person_id: str, namespace: str = None) -> List[Dict]:
    """Get all relationships for a person."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if namespace:
                cur.execute("""
                    SELECT * FROM person_relationship
                    WHERE (person_a_id = %s OR person_b_id = %s)
                      AND namespace = %s
                    ORDER BY strength DESC
                """, (person_id, person_id, namespace))
            else:
                cur.execute("""
                    SELECT * FROM person_relationship
                    WHERE person_a_id = %s OR person_b_id = %s
                    ORDER BY strength DESC
                """, (person_id, person_id))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get relationships", error=str(e))
        return []


# ============ Prompt Blueprint Functions ============

def create_blueprint(
    blueprint_id: str,
    name: str,
    use_case: str,
    template: str,
    description: str = None,
    variables_schema: List[Dict] = None,
    is_default: bool = False,
    created_by: str = "system"
) -> Dict:
    """
    Create a new prompt blueprint with initial version.

    Args:
        blueprint_id: Unique identifier (e.g., "morning_briefing_v1")
        name: Human-readable name
        use_case: Category (briefing, email, decision, coaching, analysis)
        template: Prompt template with {{placeholders}}
        description: Optional description
        variables_schema: List of variable definitions [{name, type, required, default, description}]
        is_default: Whether this is the default blueprint for the use_case
        created_by: Who created it
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # If setting as default, unset other defaults for this use_case
            if is_default:
                cur.execute("""
                    UPDATE prompt_blueprint SET is_default = false
                    WHERE use_case = %s AND is_default = true
                """, (use_case,))

            # Create blueprint
            cur.execute("""
                INSERT INTO prompt_blueprint
                (blueprint_id, name, description, use_case, template, variables_schema,
                 is_default, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)
                RETURNING id
            """, (
                blueprint_id, name, description, use_case, template,
                json.dumps(variables_schema or []), is_default, created_by
            ))
            bp_id = cur.fetchone()["id"]

            # Create initial version
            cur.execute("""
                INSERT INTO prompt_blueprint_version
                (blueprint_id, version_number, template, variables_schema,
                 changed_by, change_type)
                VALUES (%s, 1, %s, %s, %s, 'create')
                RETURNING id
            """, (bp_id, template, json.dumps(variables_schema or []), created_by))
            version_id = cur.fetchone()["id"]

            # Link version to blueprint
            cur.execute("""
                UPDATE prompt_blueprint SET current_version_id = %s WHERE id = %s
            """, (version_id, bp_id))

            log_with_context(logger, "info", "Blueprint created",
                           blueprint_id=blueprint_id, use_case=use_case)

            return {
                "status": "created",
                "id": bp_id,
                "blueprint_id": blueprint_id,
                "version_id": version_id
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to create blueprint", error=str(e))
        return {"status": "error", "error": str(e)}


def update_blueprint(
    blueprint_id: str,
    template: str = None,
    variables_schema: List[Dict] = None,
    change_reason: str = None,
    changed_by: str = "system"
) -> Dict:
    """
    Create a new version of a blueprint.

    Args:
        blueprint_id: The blueprint to update
        template: New template (or None to keep current)
        variables_schema: New variables schema (or None to keep current)
        change_reason: Why this change was made
        changed_by: Who made the change
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current blueprint
            cur.execute("""
                SELECT pb.id, pb.current_version_id, pbv.template, pbv.variables_schema,
                       pbv.version_number
                FROM prompt_blueprint pb
                JOIN prompt_blueprint_version pbv ON pb.current_version_id = pbv.id
                WHERE pb.blueprint_id = %s
            """, (blueprint_id,))
            row = cur.fetchone()

            if not row:
                return {"status": "error", "error": "Blueprint not found"}

            bp_id = row["id"]
            current_version = row["version_number"]
            new_template = template if template is not None else row["template"]
            new_vars = variables_schema if variables_schema is not None else row["variables_schema"]

            # Create new version
            cur.execute("""
                INSERT INTO prompt_blueprint_version
                (blueprint_id, version_number, template, variables_schema,
                 changed_by, change_reason, change_type)
                VALUES (%s, %s, %s, %s, %s, %s, 'edit')
                RETURNING id
            """, (
                bp_id, current_version + 1, new_template, json.dumps(new_vars),
                changed_by, change_reason
            ))
            version_id = cur.fetchone()["id"]

            # Update blueprint to point to new version
            cur.execute("""
                UPDATE prompt_blueprint
                SET current_version_id = %s, template = %s, variables_schema = %s, updated_at = NOW()
                WHERE id = %s
            """, (version_id, new_template, json.dumps(new_vars), bp_id))

            log_with_context(logger, "info", "Blueprint updated",
                           blueprint_id=blueprint_id, version=current_version + 1)

            return {
                "status": "updated",
                "blueprint_id": blueprint_id,
                "new_version": current_version + 1,
                "version_id": version_id
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to update blueprint", error=str(e))
        return {"status": "error", "error": str(e)}


def get_blueprint(blueprint_id: str = None, use_case: str = None, get_default: bool = False) -> Optional[Dict]:
    """
    Get a blueprint by ID or get the default for a use case.

    Args:
        blueprint_id: Specific blueprint ID
        use_case: Use case to find default for
        get_default: If True, get the default blueprint for use_case
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            if blueprint_id:
                cur.execute("""
                    SELECT pb.*, pbv.version_number, pbv.usage_count, pbv.avg_quality_score
                    FROM prompt_blueprint pb
                    LEFT JOIN prompt_blueprint_version pbv ON pb.current_version_id = pbv.id
                    WHERE pb.blueprint_id = %s
                """, (blueprint_id,))
            elif use_case and get_default:
                cur.execute("""
                    SELECT pb.*, pbv.version_number, pbv.usage_count, pbv.avg_quality_score
                    FROM prompt_blueprint pb
                    LEFT JOIN prompt_blueprint_version pbv ON pb.current_version_id = pbv.id
                    WHERE pb.use_case = %s AND pb.is_default = true AND pb.status = 'active'
                """, (use_case,))
            else:
                return None

            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to get blueprint", error=str(e))
        return None


def list_blueprints(use_case: str = None, status: str = "active") -> List[Dict]:
    """List all blueprints, optionally filtered by use_case and status."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = """
                SELECT pb.*, pbv.version_number, pbv.usage_count, pbv.avg_quality_score
                FROM prompt_blueprint pb
                LEFT JOIN prompt_blueprint_version pbv ON pb.current_version_id = pbv.id
                WHERE pb.status = %s
            """
            params = [status]

            if use_case:
                query += " AND pb.use_case = %s"
                params.append(use_case)

            query += " ORDER BY pb.is_default DESC, pb.updated_at DESC"

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to list blueprints", error=str(e))
        return []


def get_blueprint_versions(blueprint_id: str, limit: int = 10) -> List[Dict]:
    """Get version history for a blueprint."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT pbv.*
                FROM prompt_blueprint_version pbv
                JOIN prompt_blueprint pb ON pb.id = pbv.blueprint_id
                WHERE pb.blueprint_id = %s
                ORDER BY pbv.version_number DESC
                LIMIT %s
            """, (blueprint_id, limit))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get blueprint versions", error=str(e))
        return []


def render_blueprint(blueprint_id: str, variables: Dict[str, Any]) -> Optional[str]:
    """
    Render a blueprint template with provided variables.

    Args:
        blueprint_id: The blueprint to render
        variables: Dict of variable values to substitute

    Returns:
        Rendered template string or None on error
    """
    try:
        blueprint = get_blueprint(blueprint_id=blueprint_id)
        if not blueprint:
            return None

        template = blueprint["template"]
        schema = blueprint.get("variables_schema") or []

        # Apply defaults from schema
        final_vars = {}
        for var_def in schema:
            var_name = var_def.get("name")
            if var_name:
                if var_name in variables:
                    final_vars[var_name] = variables[var_name]
                elif var_def.get("default") is not None:
                    final_vars[var_name] = var_def["default"]
                elif var_def.get("required", False):
                    log_with_context(logger, "warning", "Required variable missing",
                                   blueprint_id=blueprint_id, variable=var_name)

        # Simple {{variable}} substitution
        result = template
        for var_name, var_value in final_vars.items():
            result = result.replace(f"{{{{{var_name}}}}}", str(var_value))

        return result
    except Exception as e:
        log_with_context(logger, "error", "Failed to render blueprint", error=str(e))
        return None


def log_blueprint_usage(
    blueprint_id: str,
    user_id: str = None,
    conversation_id: str = None,
    variables_provided: Dict = None,
    tokens_used: int = None,
    quality_score: float = None
) -> bool:
    """Log usage of a blueprint for analytics."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get blueprint and version IDs
            cur.execute("""
                SELECT id, current_version_id, use_case
                FROM prompt_blueprint WHERE blueprint_id = %s
            """, (blueprint_id,))
            row = cur.fetchone()
            if not row:
                return False

            bp_id = row["id"]
            version_id = row["current_version_id"]
            use_case = row["use_case"]

            # Log usage
            cur.execute("""
                INSERT INTO blueprint_usage
                (blueprint_id, version_id, user_id, conversation_id, use_case,
                 variables_provided, tokens_used, quality_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                bp_id, version_id, user_id, conversation_id, use_case,
                json.dumps(variables_provided or {}), tokens_used, quality_score
            ))

            # Update version usage count
            if version_id:
                cur.execute("""
                    UPDATE prompt_blueprint_version
                    SET usage_count = COALESCE(usage_count, 0) + 1
                    WHERE id = %s
                """, (version_id,))

            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to log blueprint usage", error=str(e))
        return False


# ============ A/B Test Functions ============

def create_ab_test(
    test_id: str,
    name: str,
    blueprint_id: str,
    variant_a_version: int,
    variant_b_version: int,
    success_metric: str = "user_rating",
    description: str = None,
    traffic_split: float = 0.5,
    min_samples: int = 30,
    confidence_threshold: float = 0.95,
    created_by: str = "system"
) -> Dict:
    """
    Create a new A/B test for a blueprint.

    Args:
        test_id: Unique test identifier
        name: Human-readable name
        blueprint_id: The blueprint being tested
        variant_a_version: Version number for variant A
        variant_b_version: Version number for variant B
        success_metric: What to measure (user_rating, task_completion, response_quality)
        description: Test description
        traffic_split: Percentage of traffic to variant B (0.0-1.0)
        min_samples: Minimum samples before declaring winner
        confidence_threshold: Required statistical confidence
        created_by: Who created the test
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get blueprint ID
            cur.execute("SELECT id FROM prompt_blueprint WHERE blueprint_id = %s", (blueprint_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "error": "Blueprint not found"}
            bp_id = row["id"]

            # Get version IDs
            cur.execute("""
                SELECT id, version_number FROM prompt_blueprint_version
                WHERE blueprint_id = %s AND version_number IN (%s, %s)
            """, (bp_id, variant_a_version, variant_b_version))
            versions = {r["version_number"]: r["id"] for r in cur.fetchall()}

            if variant_a_version not in versions or variant_b_version not in versions:
                return {"status": "error", "error": "Version(s) not found"}

            # Create test
            cur.execute("""
                INSERT INTO ab_test
                (test_id, name, description, blueprint_id,
                 variant_a_version, variant_b_version, traffic_split,
                 success_metric, min_samples, confidence_threshold, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                test_id, name, description, bp_id,
                versions[variant_a_version], versions[variant_b_version], traffic_split,
                success_metric, min_samples, confidence_threshold, created_by
            ))
            test_db_id = cur.fetchone()["id"]

            log_with_context(logger, "info", "A/B test created",
                           test_id=test_id, blueprint=blueprint_id)

            return {
                "status": "created",
                "id": test_db_id,
                "test_id": test_id,
                "variant_a": variant_a_version,
                "variant_b": variant_b_version
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to create A/B test", error=str(e))
        return {"status": "error", "error": str(e)}


def start_ab_test(test_id: str) -> Dict:
    """Start an A/B test (change status from draft to running)."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ab_test
                SET status = 'running', started_at = NOW(), updated_at = NOW()
                WHERE test_id = %s AND status = 'draft'
                RETURNING *
            """, (test_id,))
            row = cur.fetchone()
            if row:
                log_with_context(logger, "info", "A/B test started", test_id=test_id)
                return {"status": "started", "test": dict(row)}
            return {"status": "error", "error": "Test not found or not in draft status"}
    except Exception as e:
        log_with_context(logger, "error", "Failed to start A/B test", error=str(e))
        return {"status": "error", "error": str(e)}


def get_ab_test_variant(test_id: str, user_id: str) -> Optional[str]:
    """
    Get the variant assignment for a user in a test.
    Creates a deterministic assignment if not exists.

    Args:
        test_id: The test ID
        user_id: User identifier

    Returns:
        "A" or "B", or None if test not found/not running
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get test info
            cur.execute("""
                SELECT id, traffic_split, status FROM ab_test
                WHERE test_id = %s
            """, (test_id,))
            test = cur.fetchone()

            if not test or test["status"] != "running":
                return None

            test_db_id = test["id"]

            # Check existing assignment
            cur.execute("""
                SELECT variant FROM ab_test_assignment
                WHERE test_id = %s AND user_id = %s
            """, (test_db_id, user_id))
            existing = cur.fetchone()

            if existing:
                return existing["variant"]

            # Create deterministic assignment based on hash
            import hashlib
            hash_input = f"{test_id}:{user_id}"
            hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            variant = "B" if (hash_val % 100) / 100.0 < test["traffic_split"] else "A"

            # Store assignment
            cur.execute("""
                INSERT INTO ab_test_assignment (test_id, user_id, variant)
                VALUES (%s, %s, %s)
                ON CONFLICT (test_id, user_id) DO NOTHING
            """, (test_db_id, user_id, variant))

            return variant
    except Exception as e:
        log_with_context(logger, "error", "Failed to get A/B variant", error=str(e))
        return None


def record_ab_result(
    test_id: str,
    user_id: str,
    quality_score: float = None,
    task_completed: bool = None,
    tokens_used: int = None,
    response_time_ms: int = None,
    feedback_type: str = None,
    feedback_text: str = None,
    conversation_id: str = None,
    message_id: str = None
) -> bool:
    """Record a result for an A/B test interaction."""
    try:
        variant = get_ab_test_variant(test_id, user_id)
        if not variant:
            return False

        with get_conn() as conn:
            cur = conn.cursor()

            # Get test and assignment IDs
            cur.execute("SELECT id FROM ab_test WHERE test_id = %s", (test_id,))
            test = cur.fetchone()
            if not test:
                return False

            test_db_id = test["id"]

            cur.execute("""
                SELECT id FROM ab_test_assignment
                WHERE test_id = %s AND user_id = %s
            """, (test_db_id, user_id))
            assignment = cur.fetchone()
            assignment_id = assignment["id"] if assignment else None

            # Record result
            cur.execute("""
                INSERT INTO ab_test_result
                (test_id, assignment_id, user_id, variant, conversation_id, message_id,
                 quality_score, task_completed, tokens_used, response_time_ms,
                 feedback_type, feedback_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                test_db_id, assignment_id, user_id, variant, conversation_id, message_id,
                quality_score, task_completed, tokens_used, response_time_ms,
                feedback_type, feedback_text
            ))

            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to record A/B result", error=str(e))
        return False


def get_ab_test_stats(test_id: str) -> Dict:
    """Get statistics for an A/B test."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get test info
            cur.execute("""
                SELECT abt.*, pb.blueprint_id as blueprint_name
                FROM ab_test abt
                JOIN prompt_blueprint pb ON abt.blueprint_id = pb.id
                WHERE abt.test_id = %s
            """, (test_id,))
            test = cur.fetchone()

            if not test:
                return {"status": "error", "error": "Test not found"}

            test_db_id = test["id"]

            # Get variant stats
            cur.execute("""
                SELECT
                    variant,
                    COUNT(*) as sample_count,
                    AVG(quality_score) as avg_quality,
                    STDDEV(quality_score) as stddev_quality,
                    AVG(tokens_used) as avg_tokens,
                    AVG(response_time_ms) as avg_response_time,
                    SUM(CASE WHEN task_completed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) as completion_rate,
                    SUM(CASE WHEN feedback_type = 'thumbs_up' THEN 1 ELSE 0 END) as thumbs_up,
                    SUM(CASE WHEN feedback_type = 'thumbs_down' THEN 1 ELSE 0 END) as thumbs_down
                FROM ab_test_result
                WHERE test_id = %s
                GROUP BY variant
            """, (test_db_id,))

            stats_by_variant = {r["variant"]: dict(r) for r in cur.fetchall()}

            # Calculate statistical significance (simple z-test for proportions)
            a_stats = stats_by_variant.get("A", {})
            b_stats = stats_by_variant.get("B", {})

            significance = None
            if a_stats and b_stats:
                n_a = a_stats.get("sample_count", 0)
                n_b = b_stats.get("sample_count", 0)
                if n_a >= 5 and n_b >= 5:
                    import math
                    avg_a = a_stats.get("avg_quality") or 0
                    avg_b = b_stats.get("avg_quality") or 0
                    std_a = a_stats.get("stddev_quality") or 0
                    std_b = b_stats.get("stddev_quality") or 0

                    if std_a > 0 or std_b > 0:
                        pooled_se = math.sqrt((std_a**2 / n_a) + (std_b**2 / n_b)) if n_a > 0 and n_b > 0 else 1
                        if pooled_se > 0:
                            z_score = (avg_b - avg_a) / pooled_se
                            # Approximate p-value (two-tailed)
                            # Using simple approximation for |z| < 3
                            p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z_score) / math.sqrt(2))))
                            significance = {
                                "z_score": z_score,
                                "p_value": p_value,
                                "significant": p_value < (1 - test["confidence_threshold"]),
                                "winner": "B" if z_score > 0 and p_value < 0.05 else ("A" if z_score < 0 and p_value < 0.05 else None),
                                "min_samples_reached": min(n_a, n_b) >= test["min_samples"]
                            }

            return {
                "test": dict(test),
                "variant_a": a_stats,
                "variant_b": b_stats,
                "total_samples": (a_stats.get("sample_count", 0) + b_stats.get("sample_count", 0)),
                "significance": significance
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to get A/B test stats", error=str(e))
        return {"status": "error", "error": str(e)}


def complete_ab_test(test_id: str, winner: str = None, notes: str = None) -> Dict:
    """
    Complete an A/B test and optionally promote the winner.

    Args:
        test_id: The test to complete
        winner: "A", "B", or None for no winner
        notes: Conclusion notes
    """
    try:
        stats = get_ab_test_stats(test_id)
        if stats.get("status") == "error":
            return stats

        sig = stats.get("significance", {})
        final_winner = winner or sig.get("winner")
        confidence = sig.get("p_value", 1.0) if sig else 1.0

        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                UPDATE ab_test
                SET status = 'completed',
                    ended_at = NOW(),
                    winner_variant = %s,
                    winner_confidence = %s,
                    conclusion_notes = %s,
                    updated_at = NOW()
                WHERE test_id = %s
                RETURNING *
            """, (final_winner, 1 - confidence if confidence < 1 else None, notes, test_id))

            row = cur.fetchone()
            if not row:
                return {"status": "error", "error": "Test not found"}

            log_with_context(logger, "info", "A/B test completed",
                           test_id=test_id, winner=final_winner)

            return {
                "status": "completed",
                "test": dict(row),
                "winner": final_winner,
                "stats": stats
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to complete A/B test", error=str(e))
        return {"status": "error", "error": str(e)}


def list_ab_tests(status: str = None, blueprint_id: str = None) -> List[Dict]:
    """List A/B tests with optional filters."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            query = """
                SELECT abt.*, pb.blueprint_id as blueprint_name
                FROM ab_test abt
                JOIN prompt_blueprint pb ON abt.blueprint_id = pb.id
                WHERE 1=1
            """
            params = []

            if status:
                query += " AND abt.status = %s"
                params.append(status)

            if blueprint_id:
                query += " AND pb.blueprint_id = %s"
                params.append(blueprint_id)

            query += " ORDER BY abt.created_at DESC"

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to list A/B tests", error=str(e))
        return []


# =============================================================================
# PERSON SEARCH (Phase 18.x - Person Entity Search Integration)
# =============================================================================

def search_persons(
    name: Optional[str] = None,
    email: Optional[str] = None,
    birthday: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search person profiles using person_identifier table.
    
    Args:
        name: Search by full_name or first/last name (partial match)
        email: Search by email (exact match after normalization)
        birthday: Search by birthday (YYYY-MM-DD format)
        limit: Max results per query
    
    Returns:
        List of matching person profiles with their identifiers
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Build search query using person_identifier table
                query = """
                    SELECT DISTINCT
                        pp.person_id,
                        pp.name,
                        pp.birthday,
                        COUNT(DISTINCT pi.identifier_type) as identifier_count,
                        MAX(pi.confidence) as max_confidence,
                        pp.created_at,
                        pp.updated_at
                    FROM person_profile pp
                    LEFT JOIN person_identifier pi ON pp.person_id = pi.person_id
                    WHERE 1=1
                """
                
                params = []
                
                # Search by name (full_name, first_name, or last_name)
                if name:
                    name_pattern = f"%{name.lower()}%"
                    query += """
                        AND (
                            LOWER(pp.name) LIKE %s
                            OR EXISTS (
                                SELECT 1 FROM person_identifier pi2
                                WHERE pi2.person_id = pp.person_id
                                AND pi2.identifier_type IN ('full_name', 'first_name', 'last_name')
                                AND LOWER(pi2.normalized_value) LIKE %s
                            )
                        )
                    """
                    params.extend([name_pattern, name_pattern])
                
                # Search by email (exact match after normalization)
                if email:
                    email_lower = email.lower()
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM person_identifier pi3
                            WHERE pi3.person_id = pp.person_id
                            AND pi3.identifier_type = 'email'
                            AND pi3.normalized_value = %s
                        )
                    """
                    params.append(email_lower)
                
                # Search by birthday
                if birthday:
                    query += """
                        AND (
                            pp.birthday = %s::DATE
                            OR EXISTS (
                                SELECT 1 FROM person_identifier pi4
                                WHERE pi4.person_id = pp.person_id
                                AND pi4.identifier_type = 'birthday'
                                AND pi4.identifier_value = %s
                            )
                        )
                    """
                    params.extend([birthday, birthday])
                
                query += " GROUP BY pp.person_id ORDER BY max_confidence DESC, pp.updated_at DESC LIMIT %s"
                params.append(limit)
                
                log_with_context(logger, "info", "Executing search query", query_params=params, query_snippet=query[:200])
                cur.execute(query, params)
                results = [dict(row) for row in cur.fetchall()]
                log_with_context(logger, "info", "Search query returned", result_count=len(results))
                
                # Enrich results with identifiers
                for person in results:
                    person['identifiers'] = get_person_identifiers(person['person_id'])
                
                return results
    except Exception as e:
        log_with_context(logger, "error", "Person search failed", error=str(e), 
                       name=name, email=email, birthday=birthday)
        return []


def get_person_identifiers(person_id: str) -> List[Dict[str, Any]]:
    """Get all identifiers for a person (search index)"""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT
                        identifier_type,
                        identifier_value,
                        normalized_value,
                        confidence,
                        status,
                        created_at
                    FROM person_identifier
                    WHERE person_id = %s
                    ORDER BY confidence DESC, created_at DESC
                """
                cur.execute(query, [person_id])
                return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get person identifiers", error=str(e), person_id=person_id)
        return []


def add_person_observation(
    person_id: str,
    field_path: str,
    observed_value: str,
    confidence: float = 0.50,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None
) -> bool:
    """
    Record a new observation for a person (validation pipeline: tbc -> validated -> confirmed).
    
    Args:
        person_id: Target person
        field_path: Field being observed (e.g., 'relationship.role', 'preferences.style')
        observed_value: Value observed
        confidence: Confidence score (0.0-1.0)
        source_type: Source of observation (chat, email, document, etc.)
        source_id: Reference to source document
        evidence_refs: Links to evidence
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                query = """
                    INSERT INTO person_observation
                    (person_id, field_path, observed_value, confidence, validation_status, 
                     source_type, source_id, evidence_refs, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'tbc', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (person_id, field_path) DO UPDATE SET
                        observed_value = EXCLUDED.observed_value,
                        confidence = EXCLUDED.confidence,
                        last_observed_at = NOW(),
                        updated_at = NOW()
                """
                cur.execute(query, [
                    person_id,
                    field_path,
                    observed_value,
                    confidence,
                    source_type,
                    source_id,
                    json.dumps(evidence_refs) if evidence_refs else None
                ])
                return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to add person observation", error=str(e),
                       person_id=person_id, field_path=field_path)
        return False


def link_evidence_to_knowledge(
    item_type: str,  # profile_version|insight_note|memory
    item_id: str,
    evidence_type: str,  # chat|email|document|qdrant
    evidence_ref: str,  # Reference to evidence
    source_path: Optional[str] = None,
    namespace: Optional[str] = None
) -> bool:
    """Link evidence source to a knowledge item for traceability"""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                query = """
                    INSERT INTO knowledge_evidence_link
                    (item_type, item_id, evidence_type, evidence_ref, source_path, namespace, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT DO NOTHING
                """
                cur.execute(query, [item_type, item_id, evidence_type, evidence_ref, source_path, namespace])
                return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to link evidence", error=str(e),
                       item_type=item_type, item_id=item_id, evidence_ref=evidence_ref)
        return False


def learn_from_observation(
    person_id: str,
    field_path: str,
    observed_value: str,
    confidence: float = 0.70,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None,
    auto_validate: bool = False
) -> Dict[str, Any]:
    """
    Learn from a new observation about a person (e.g., from chat, email, document).
    
    Implements validation pipeline:
    - tbc (to-be-confirmed): New observations with confidence < threshold
    - validated: Observations matching existing identifier with confidence boost
    - confirmed: High-confidence observations from trusted sources
    
    Returns status dict with learning_id, validation_status, confidence_trend
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Step 1: Record the observation
                observation_id = add_person_observation(
                    person_id=person_id,
                    field_path=field_path,
                    observed_value=observed_value,
                    confidence=confidence,
                    source_type=source_type,
                    source_id=source_id,
                    evidence_refs=evidence_refs
                )
                
                # Step 2: Check if matches existing identifier
                validation_status = "tbc"  # default: to-be-confirmed
                confidence_boost = 0.0
                
                # For name-related fields, try to match in person_identifier
                if field_path in ['name', 'first_name', 'last_name', 'full_name']:
                    cur.execute("""
                        SELECT confidence, status FROM person_identifier
                        WHERE person_id = %s AND identifier_type IN (%s, %s)
                        AND normalized_value = %s
                    """, (person_id, 'full_name', field_path, observed_value.lower()))
                    existing = cur.fetchone()
                    
                    if existing:
                        # Already known: boost confidence if consistent
                        validation_status = "validated"
                        confidence_boost = min(0.15, 1.0 - existing['confidence'])  # Boost up to 15% or to 1.0
                        new_confidence = min(1.0, confidence + confidence_boost)
                        
                        # Update identifier confidence
                        cur.execute("""
                            UPDATE person_identifier
                            SET confidence = %s, last_observed_at = NOW()
                            WHERE person_id = %s AND identifier_value = %s
                        """, (new_confidence, person_id, observed_value))
                
                # Step 3: Auto-validate if trusted source and high confidence
                if auto_validate and confidence >= 0.85:
                    validation_status = "confirmed"
                
                # Step 4: Link evidence to knowledge items
                if evidence_refs:
                    for evidence_ref in evidence_refs:
                        link_evidence_to_knowledge(
                            item_type='observation',
                            item_id=str(observation_id),
                            evidence_type=source_type or 'manual',
                            evidence_ref=evidence_ref,
                            source_path=source_id,
                            namespace='person_learning'
                        )
                
                log_with_context(logger, "info", "Person learning recorded",
                               person_id=person_id, field_path=field_path,
                               validation_status=validation_status,
                               confidence_boost=confidence_boost)
                
                return {
                    "learning_id": observation_id,
                    "field_path": field_path,
                    "validation_status": validation_status,
                    "confidence_boost": confidence_boost,
                    "evidence_count": len(evidence_refs) if evidence_refs else 0,
                    "success": True
                }
    
    except Exception as e:
        log_with_context(logger, "error", "Failed to learn from observation", error=str(e),
                       person_id=person_id, field_path=field_path)
        return {
            "learning_id": None,
            "success": False,
            "error": str(e)
        }
