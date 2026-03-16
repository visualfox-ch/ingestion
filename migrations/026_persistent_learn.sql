-- Migration 026: Persistent Learn schema (learned_facts, decision_logs, pattern_history)

CREATE TABLE IF NOT EXISTS learned_facts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    value_text TEXT,
    source TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    sensitivity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    reason TEXT,
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_learned_facts_user ON learned_facts(user_id, namespace);
CREATE INDEX IF NOT EXISTS idx_learned_facts_key ON learned_facts(key);
CREATE INDEX IF NOT EXISTS idx_learned_facts_status ON learned_facts(status);
CREATE INDEX IF NOT EXISTS idx_learned_facts_expires ON learned_facts(expires_at);

CREATE TABLE IF NOT EXISTS decision_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    decision_text TEXT NOT NULL,
    outcome TEXT,
    confidence DOUBLE PRECISION,
    source TEXT NOT NULL,
    context JSONB,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_decision_logs_user ON decision_logs(user_id, namespace);
CREATE INDEX IF NOT EXISTS idx_decision_logs_decision ON decision_logs(decision_id);
CREATE INDEX IF NOT EXISTS idx_decision_logs_expires ON decision_logs(expires_at);

CREATE TABLE IF NOT EXISTS pattern_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    pattern_key TEXT NOT NULL,
    pattern_data JSONB NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    score DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pattern_history_user ON pattern_history(user_id, namespace);
CREATE INDEX IF NOT EXISTS idx_pattern_history_key ON pattern_history(pattern_key);
CREATE INDEX IF NOT EXISTS idx_pattern_history_expires ON pattern_history(expires_at);
