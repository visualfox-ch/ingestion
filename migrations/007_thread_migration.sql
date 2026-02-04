-- Migration 007: Thread state migration from SQLite to PostgreSQL
-- Phase 15.5: Consolidate conversation thread tracking
--
-- This migration creates PostgreSQL tables to replace the following
-- SQLite tables from session_manager.py:
-- - conversation_contexts
-- - thread_state
-- - topic_mentions
-- - pending_actions

-- Conversation context summaries (session-level)
CREATE TABLE IF NOT EXISTS conversation_context (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    namespace TEXT DEFAULT 'private',
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    conversation_summary TEXT,
    key_topics JSONB DEFAULT '[]',
    pending_actions JSONB DEFAULT '[]',
    emotional_indicators JSONB DEFAULT '[]',
    relationship_updates JSONB DEFAULT '[]',
    message_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_context_session ON conversation_context(session_id);
CREATE INDEX IF NOT EXISTS idx_context_user ON conversation_context(user_id);
CREATE INDEX IF NOT EXISTS idx_context_namespace ON conversation_context(namespace);
CREATE INDEX IF NOT EXISTS idx_context_start ON conversation_context(start_time DESC);

-- Thread state tracking (topic lifecycle)
CREATE TABLE IF NOT EXISTS thread_state_pg (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'paused')),
    opened_at TIMESTAMP,
    closed_at TIMESTAMP,
    paused_at TIMESTAMP,
    session_id TEXT,
    last_activity TIMESTAMP DEFAULT NOW(),
    priority TEXT DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, topic)
);

CREATE INDEX IF NOT EXISTS idx_thread_pg_user ON thread_state_pg(user_id);
CREATE INDEX IF NOT EXISTS idx_thread_pg_status ON thread_state_pg(status);
CREATE INDEX IF NOT EXISTS idx_thread_pg_activity ON thread_state_pg(last_activity DESC);
CREATE INDEX IF NOT EXISTS idx_thread_pg_session ON thread_state_pg(session_id);

-- Topic mentions frequency tracking
CREATE TABLE IF NOT EXISTS topic_mention (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    first_mentioned TIMESTAMP DEFAULT NOW(),
    last_mentioned TIMESTAMP DEFAULT NOW(),
    context_snippet TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topic_user ON topic_mention(user_id);
CREATE INDEX IF NOT EXISTS idx_topic_name ON topic_mention(topic);
CREATE INDEX IF NOT EXISTS idx_topic_session ON topic_mention(session_id);
CREATE INDEX IF NOT EXISTS idx_topic_last_mentioned ON topic_mention(last_mentioned DESC);

-- Pending actions from conversations
CREATE TABLE IF NOT EXISTS pending_action_pg (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action_text TEXT NOT NULL,
    context TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    due_date TIMESTAMP,
    completed_at TIMESTAMP,
    completed BOOLEAN DEFAULT FALSE,
    priority TEXT DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    FOREIGN KEY (session_id) REFERENCES conversation_context(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_action_pg(user_id);
CREATE INDEX IF NOT EXISTS idx_pending_completed ON pending_action_pg(completed);
CREATE INDEX IF NOT EXISTS idx_pending_due ON pending_action_pg(due_date);
CREATE INDEX IF NOT EXISTS idx_pending_session ON pending_action_pg(session_id);

-- Migration status tracking
CREATE TABLE IF NOT EXISTS thread_migration_status (
    id SERIAL PRIMARY KEY,
    migration_name TEXT UNIQUE NOT NULL,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    source_counts JSONB,
    migrated_counts JSONB,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT
);

-- Insert migration record
INSERT INTO thread_migration_status (migration_name, status)
VALUES ('007_thread_migration', 'pending')
ON CONFLICT (migration_name) DO NOTHING;
