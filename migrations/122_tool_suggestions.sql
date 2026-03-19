-- Migration: Tool Suggestions System
-- Phase 21 Option 2B: Smart Tool Suggestions
-- Date: 2026-03-18

-- Table for storing suggestion feedback (for learning)
CREATE TABLE IF NOT EXISTS jarvis_tool_suggestion_feedback (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR(100) NOT NULL,
    was_helpful BOOLEAN NOT NULL,
    session_id VARCHAR(100),
    query_preview TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_suggestion_feedback_tool ON jarvis_tool_suggestion_feedback(tool_name);
CREATE INDEX IF NOT EXISTS idx_suggestion_feedback_time ON jarvis_tool_suggestion_feedback(created_at DESC);

-- Table for tracking which suggestions were shown (for analysis)
CREATE TABLE IF NOT EXISTS jarvis_tool_suggestions_log (
    id SERIAL PRIMARY KEY,
    query_hash VARCHAR(64),
    suggested_tools TEXT[],
    used_tools TEXT[],
    similarity_scores FLOAT[],
    session_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_suggestions_log_time ON jarvis_tool_suggestions_log(created_at DESC);

-- View for analyzing suggestion effectiveness
CREATE OR REPLACE VIEW v_suggestion_effectiveness AS
SELECT
    tool_name,
    COUNT(*) as total_suggestions,
    COUNT(CASE WHEN was_helpful THEN 1 END) as helpful_count,
    ROUND(COUNT(CASE WHEN was_helpful THEN 1 END)::float / NULLIF(COUNT(*), 0) * 100, 1) as helpful_rate
FROM jarvis_tool_suggestion_feedback
GROUP BY tool_name
ORDER BY total_suggestions DESC;

-- Comments
COMMENT ON TABLE jarvis_tool_suggestion_feedback IS 'Phase 21 2B: Feedback on tool suggestions for learning';
COMMENT ON TABLE jarvis_tool_suggestions_log IS 'Phase 21 2B: Log of suggestions shown for analysis';
