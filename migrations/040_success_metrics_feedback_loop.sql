-- Phase 2: Success metrics feedback loop (T-20260207-403)
-- Adds feedback tracking with source + strategy/tool labels
-- NOTE: decision_outcomes already exists for AI-1 Context Engine (UUID-based)
-- This creates a separate table for explicit success/fail feedback

CREATE TABLE IF NOT EXISTS feedback_outcomes (
    id BIGSERIAL PRIMARY KEY,
    decision_id TEXT NOT NULL,
    user_id INTEGER,
    session_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('success','fail','unknown')),
    feedback_score REAL,
    source_channel TEXT NOT NULL DEFAULT 'unknown',
    strategy_id TEXT DEFAULT 'unknown',
    tool_name TEXT DEFAULT 'unknown',
    details JSONB DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_outcomes_decision_id ON feedback_outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_feedback_outcomes_outcome ON feedback_outcomes(outcome);
CREATE INDEX IF NOT EXISTS idx_feedback_outcomes_strategy ON feedback_outcomes(strategy_id);
CREATE INDEX IF NOT EXISTS idx_feedback_outcomes_tool ON feedback_outcomes(tool_name);
CREATE INDEX IF NOT EXISTS idx_feedback_outcomes_source ON feedback_outcomes(source_channel);
CREATE INDEX IF NOT EXISTS idx_feedback_outcomes_user ON feedback_outcomes(user_id, recorded_at DESC);

ALTER TABLE IF EXISTS decision_log
    ADD COLUMN IF NOT EXISTS outcome_source TEXT,
    ADD COLUMN IF NOT EXISTS outcome_recorded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decision_strategy TEXT,
    ADD COLUMN IF NOT EXISTS primary_tool TEXT;
