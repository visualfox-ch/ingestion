-- Phase 16.4A: Feedback Loop System
-- Migration: 005_phase_16_4_feedback.sql
-- Created: 2026-02-01
-- Author: Claude Code

-- =============================================================================
-- FEEDBACK COLLECTION
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Feedback context
    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',
    session_id VARCHAR(100),
    message_id VARCHAR(100),

    -- What was the feedback about
    feedback_type VARCHAR(100) NOT NULL,  -- 'response', 'search', 'recommendation', 'action', 'general'
    context_type VARCHAR(100),  -- 'chat', 'email_draft', 'remediation', 'briefing'

    -- Explicit feedback
    rating INT CHECK (rating BETWEEN 1 AND 5),  -- 1-5 scale
    thumbs_up BOOLEAN,  -- Simple thumbs up/down
    feedback_text TEXT,  -- Free text feedback

    -- What was wrong/right
    feedback_tags TEXT[],  -- ['too_long', 'inaccurate', 'helpful', 'missed_context']

    -- Original content reference
    original_query TEXT,
    original_response TEXT,

    -- Follow-up
    was_corrected BOOLEAN DEFAULT false,
    correction_text TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- DECISION HISTORY
-- =============================================================================

CREATE TABLE IF NOT EXISTS decision_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Decision context
    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',
    decision_type VARCHAR(100) NOT NULL,  -- 'work_vs_personal', 'prioritize', 'delegate', 'postpone'

    -- The decision
    decision_description TEXT NOT NULL,
    options_considered JSONB,  -- [{option, pros, cons, selected}]
    chosen_option VARCHAR(500),

    -- Factors
    key_factors TEXT[],  -- What influenced the decision
    time_pressure VARCHAR(50),  -- 'urgent', 'normal', 'relaxed'
    confidence_level INT,  -- 1-5

    -- Context
    context_notes TEXT,
    related_entities JSONB,  -- People, projects involved

    -- Outcome tracking
    outcome_status VARCHAR(50),  -- 'pending', 'success', 'partial', 'failed', 'unknown'
    outcome_notes TEXT,
    outcome_recorded_at TIMESTAMPTZ,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- OUTCOME TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS outcome_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What was tracked
    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',
    source_type VARCHAR(100) NOT NULL,  -- 'decision', 'action', 'recommendation', 'email'
    source_id UUID,  -- Reference to original item

    -- Predicted vs actual
    prediction TEXT,
    predicted_confidence DECIMAL(3,2),
    actual_outcome TEXT,
    outcome_quality VARCHAR(50),  -- 'better_than_expected', 'as_expected', 'worse_than_expected'

    -- Metrics
    success_score DECIMAL(3,2),  -- 0.0-1.0

    -- Learning
    lessons_learned TEXT,
    should_repeat BOOLEAN,
    adjustment_needed TEXT,

    -- Metadata
    tracked_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- JARVIS SELF-IMPROVEMENT LOG
-- =============================================================================

CREATE TABLE IF NOT EXISTS self_improvement_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What was improved
    improvement_type VARCHAR(100) NOT NULL,  -- 'prompt_adjustment', 'behavior_change', 'capability_added'
    description TEXT NOT NULL,

    -- Evidence
    trigger_feedback_ids UUID[],  -- Feedback that triggered this improvement
    evidence_summary TEXT,

    -- Impact
    expected_impact TEXT,
    actual_impact TEXT,
    impact_measured_at TIMESTAMPTZ,

    -- Status
    status VARCHAR(50) DEFAULT 'proposed',  -- 'proposed', 'testing', 'active', 'reverted'

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Feedback indexes
CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_session ON user_feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON user_feedback(feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON user_feedback(rating);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON user_feedback(created_at DESC);

-- Decision indexes
CREATE INDEX IF NOT EXISTS idx_decision_user ON decision_history(user_id);
CREATE INDEX IF NOT EXISTS idx_decision_type ON decision_history(decision_type);
CREATE INDEX IF NOT EXISTS idx_decision_outcome ON decision_history(outcome_status);
CREATE INDEX IF NOT EXISTS idx_decision_created ON decision_history(created_at DESC);

-- Outcome indexes
CREATE INDEX IF NOT EXISTS idx_outcome_user ON outcome_tracking(user_id);
CREATE INDEX IF NOT EXISTS idx_outcome_source ON outcome_tracking(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_outcome_quality ON outcome_tracking(outcome_quality);

-- Self-improvement indexes
CREATE INDEX IF NOT EXISTS idx_improvement_type ON self_improvement_log(improvement_type);
CREATE INDEX IF NOT EXISTS idx_improvement_status ON self_improvement_log(status);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to calculate feedback summary
CREATE OR REPLACE FUNCTION get_feedback_summary(
    p_user_id VARCHAR(100) DEFAULT 'micha',
    p_days INT DEFAULT 30
) RETURNS TABLE (
    total_feedback BIGINT,
    avg_rating NUMERIC,
    positive_count BIGINT,
    negative_count BIGINT,
    top_tags TEXT[]
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT as total_feedback,
        ROUND(AVG(rating)::NUMERIC, 2) as avg_rating,
        COUNT(*) FILTER (WHERE thumbs_up = true OR rating >= 4)::BIGINT as positive_count,
        COUNT(*) FILTER (WHERE thumbs_up = false OR rating <= 2)::BIGINT as negative_count,
        (SELECT ARRAY_AGG(tag) FROM (
            SELECT UNNEST(feedback_tags) as tag
            FROM user_feedback
            WHERE user_id = p_user_id AND created_at > NOW() - (p_days || ' days')::INTERVAL
            GROUP BY tag
            ORDER BY COUNT(*) DESC
            LIMIT 5
        ) t) as top_tags
    FROM user_feedback
    WHERE user_id = p_user_id AND created_at > NOW() - (p_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;

-- Function to record quick feedback
CREATE OR REPLACE FUNCTION record_quick_feedback(
    p_user_id VARCHAR(100),
    p_feedback_type VARCHAR(100),
    p_thumbs_up BOOLEAN,
    p_session_id VARCHAR(100) DEFAULT NULL,
    p_tags TEXT[] DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO user_feedback (
        user_id, feedback_type, thumbs_up, session_id, feedback_tags
    ) VALUES (
        p_user_id, p_feedback_type, p_thumbs_up, p_session_id, p_tags
    ) RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Add comments for tracking
COMMENT ON TABLE user_feedback IS 'Phase 16.4A: User feedback collection';
COMMENT ON TABLE decision_history IS 'Phase 16.4A: Decision tracking for pattern learning';
COMMENT ON TABLE outcome_tracking IS 'Phase 16.4A: Outcome tracking for prediction improvement';
COMMENT ON TABLE self_improvement_log IS 'Phase 16.4A: Jarvis self-improvement tracking';
