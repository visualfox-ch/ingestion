-- Migration for Persistent Learn Backend
-- Creates learned_facts, decision_logs, pattern_history tables

CREATE TABLE IF NOT EXISTS learned_facts (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    namespace VARCHAR(64) NOT NULL,
    key VARCHAR(128) NOT NULL,
    value JSONB NOT NULL,
    value_text TEXT,
    source VARCHAR(32) NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    sensitivity VARCHAR(16) NOT NULL DEFAULT 'low',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    reason TEXT,
    context JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    memory_tier VARCHAR(16),
    decay_date TIMESTAMP WITH TIME ZONE,
    access_count INT DEFAULT 0,
    last_accessed TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS decision_logs (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    namespace VARCHAR(64) NOT NULL,
    decision_id VARCHAR(128) NOT NULL,
    decision_text TEXT NOT NULL,
    outcome VARCHAR(32),
    confidence FLOAT,
    source VARCHAR(32),
    context JSONB,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS pattern_history (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    namespace VARCHAR(64) NOT NULL,
    pattern_key VARCHAR(64) NOT NULL,
    pattern_data JSONB NOT NULL,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
    score FLOAT,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_learned_facts_namespace ON learned_facts(namespace);
CREATE INDEX IF NOT EXISTS idx_decision_logs_namespace ON decision_logs(namespace);
CREATE INDEX IF NOT EXISTS idx_pattern_history_namespace ON pattern_history(namespace);
