-- Migration 071: Proactive Hints Table
-- Phase 19.2: Enable proactive pattern detection and hint tracking
-- Allows Jarvis to track and analyze proactive observations

CREATE TABLE IF NOT EXISTS proactive_hints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(100) NOT NULL,
    session_id VARCHAR(100),
    hint_type VARCHAR(50) NOT NULL,  -- 'pattern', 'reminder', 'suggestion', 'observation', 'warning'
    category VARCHAR(100),            -- 'productivity', 'communication', 'health', 'workflow', 'learning'
    content TEXT NOT NULL,            -- The actual hint/observation
    context TEXT,                     -- What triggered this hint
    confidence REAL DEFAULT 0.5,      -- 0.0-1.0 confidence in the hint
    was_shown BOOLEAN DEFAULT FALSE,  -- Was this hint shown to user?
    was_accepted BOOLEAN,             -- Did user find it helpful? (NULL = no feedback)
    user_feedback TEXT,               -- Optional user feedback on the hint
    metadata JSONB,                   -- Additional context (patterns detected, frequency, etc.)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    shown_at TIMESTAMPTZ,
    feedback_at TIMESTAMPTZ
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_proactive_hints_user ON proactive_hints(user_id);
CREATE INDEX IF NOT EXISTS idx_proactive_hints_type ON proactive_hints(hint_type);
CREATE INDEX IF NOT EXISTS idx_proactive_hints_created ON proactive_hints(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proactive_hints_shown ON proactive_hints(was_shown) WHERE was_shown = FALSE;
CREATE INDEX IF NOT EXISTS idx_proactive_hints_acceptance ON proactive_hints(was_accepted) WHERE was_accepted IS NOT NULL;

-- Summary view for proactivity metrics
CREATE OR REPLACE VIEW proactive_hints_summary AS
SELECT
    user_id,
    hint_type,
    COUNT(*) AS total_hints,
    COUNT(*) FILTER (WHERE was_shown) AS shown_hints,
    COUNT(*) FILTER (WHERE was_accepted = TRUE) AS accepted_hints,
    COUNT(*) FILTER (WHERE was_accepted = FALSE) AS rejected_hints,
    AVG(confidence) AS avg_confidence,
    MAX(created_at) AS last_hint_at
FROM proactive_hints
GROUP BY user_id, hint_type;

COMMENT ON TABLE proactive_hints IS 'Tracks proactive observations and suggestions from Jarvis to users';
