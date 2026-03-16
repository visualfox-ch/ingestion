-- Migration 027: Session Persistence Schema
-- Purpose: Create tables for session management and conversation history
-- Date: 2026-02-04

-- Sessions table
-- Stores session metadata and context
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    facette_weights JSONB DEFAULT '{}'::jsonb,
    learned_facts_ids INTEGER[] DEFAULT ARRAY[]::INTEGER[],
    user_preferences JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    archived_at TIMESTAMP WITH TIME ZONE,
    created_index_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_archived ON sessions(archived_at) WHERE archived_at IS NULL;

-- Conversation history table
-- Stores individual messages with timestamp and metadata
CREATE TABLE IF NOT EXISTS conversation_messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    message_index INTEGER NOT NULL,
    role VARCHAR(20) NOT NULL,  -- "user" or "assistant"
    content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb,
    token_count INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, message_index)
);

-- Create indexes for message queries
CREATE INDEX IF NOT EXISTS idx_conversation_session_id ON conversation_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_conversation_timestamp ON conversation_messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_role ON conversation_messages(role);

-- Session activity log table
-- Audit trail for session lifecycle events
CREATE TABLE IF NOT EXISTS session_activity_log (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,  -- "created", "resumed", "archived", "expired"
    description TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create index for activity queries
CREATE INDEX IF NOT EXISTS idx_activity_session_id ON session_activity_log(session_id);
CREATE INDEX IF NOT EXISTS idx_activity_type ON session_activity_log(activity_type);
CREATE INDEX IF NOT EXISTS idx_activity_created_at ON session_activity_log(created_at DESC);

-- Session statistics table
-- Pre-computed stats for performance
CREATE TABLE IF NOT EXISTS session_stats (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) UNIQUE NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    message_count INTEGER DEFAULT 0,
    user_message_count INTEGER DEFAULT 0,
    assistant_message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    avg_message_length NUMERIC(10, 2) DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create index for stats
CREATE INDEX IF NOT EXISTS idx_stats_session_id ON session_stats(session_id);

-- Add comment describing the schema
COMMENT ON TABLE sessions IS 'Session metadata and conversation context storage for persistent memory';
COMMENT ON TABLE conversation_messages IS 'Individual messages in conversation history with metadata';
COMMENT ON TABLE session_activity_log IS 'Audit trail of session lifecycle events';
COMMENT ON TABLE session_stats IS 'Pre-computed statistics for sessions';

-- Add comments for key columns
COMMENT ON COLUMN sessions.facette_weights IS 'User personality/preference weights as JSON';
COMMENT ON COLUMN sessions.learned_facts_ids IS 'References to learned_facts table for quick lookup';
COMMENT ON COLUMN sessions.expires_at IS 'Session expiration time (null = no automatic expiry)';
COMMENT ON COLUMN conversation_messages.token_count IS 'Token count for billing/quota tracking';

NOTICE 'Migration 027: Session persistence schema created successfully';
