-- Migration 039: Context-Aware Decision Engine (AI-1)
--
-- Creates tables for:
-- - context_decisions: Store decisions with full context vectors
-- - decision_outcomes: Track outcomes for learning
-- - bandit_model_parameters: Linear Thompson Sampling model state
-- - learning_insights: Generated insights from outcome analysis
--
-- Author: Claude Code
-- Date: 2026-02-06

-- Context-Aware Decisions Storage
CREATE TABLE IF NOT EXISTS context_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    decision_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Context vector (JSONB for flexibility)
    user_context JSONB NOT NULL DEFAULT '{}',
    temporal_context JSONB NOT NULL DEFAULT '{}',
    environmental_context JSONB NOT NULL DEFAULT '{}',
    historical_context JSONB NOT NULL DEFAULT '{}',

    -- Decision details
    selected_option_id TEXT NOT NULL,
    selected_option_type TEXT NOT NULL,
    selected_option_params JSONB NOT NULL DEFAULT '{}',
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    -- Alternative options considered
    alternative_options JSONB NOT NULL DEFAULT '[]',

    -- Decision reasoning
    reasoning TEXT,
    context_factors JSONB DEFAULT '[]', -- [(factor_name, influence_weight), ...]
    uncertainty_metrics JSONB DEFAULT '{}',
    expected_outcome JSONB DEFAULT '{}',

    -- Tracking
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Decision outcomes tracking
CREATE TABLE IF NOT EXISTS decision_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id UUID NOT NULL REFERENCES context_decisions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,

    -- Outcome metrics
    outcome_metrics JSONB NOT NULL DEFAULT '{}',
    user_feedback JSONB,
    success_indicators JSONB,
    reward_signal FLOAT, -- Calculated reward for learning

    -- Follow-up tracking
    follow_up_actions TEXT[],
    outcome_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Timing
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Contextual bandit model parameters (one row per arm/option)
CREATE TABLE IF NOT EXISTS bandit_model_parameters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_type TEXT NOT NULL,
    option_id TEXT NOT NULL,

    -- Linear model parameters (stored as arrays for efficiency)
    theta_mean FLOAT[] NOT NULL,
    theta_precision_matrix FLOAT[] NOT NULL, -- Flattened precision matrix
    feature_dim INTEGER NOT NULL DEFAULT 20,

    -- Model metadata
    update_count INTEGER NOT NULL DEFAULT 0,
    last_reward FLOAT,
    cumulative_reward FLOAT DEFAULT 0.0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(decision_type, option_id)
);

-- Learning insights from outcome analysis
CREATE TABLE IF NOT EXISTS learning_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight_type TEXT NOT NULL, -- "context_correlation", "option_performance", "user_pattern", "temporal_pattern"
    description TEXT NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    -- Evidence and recommendations
    supporting_evidence JSONB NOT NULL DEFAULT '{}',
    actionable_recommendation TEXT,

    -- Scope
    user_id TEXT, -- NULL = global insight
    decision_type TEXT,

    -- Metadata
    sample_size INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ, -- Insights can expire
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_context_decisions_user_timestamp
    ON context_decisions(user_id, decision_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_context_decisions_type
    ON context_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_context_decisions_created
    ON context_decisions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_decision_outcomes_decision_id
    ON decision_outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_decision_outcomes_user
    ON decision_outcomes(user_id, outcome_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_bandit_parameters_lookup
    ON bandit_model_parameters(decision_type, option_id);

CREATE INDEX IF NOT EXISTS idx_learning_insights_type_active
    ON learning_insights(insight_type, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_learning_insights_user
    ON learning_insights(user_id, created_at DESC) WHERE user_id IS NOT NULL;

-- Update trigger for context_decisions
CREATE OR REPLACE FUNCTION update_context_decisions_modified()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_context_decisions_modtime ON context_decisions;
CREATE TRIGGER update_context_decisions_modtime
    BEFORE UPDATE ON context_decisions
    FOR EACH ROW EXECUTE FUNCTION update_context_decisions_modified();

-- Add comments for documentation
COMMENT ON TABLE context_decisions IS 'AI-1: Context-aware decisions with multi-dimensional context vectors';
COMMENT ON TABLE decision_outcomes IS 'AI-1: Tracked outcomes for decision learning';
COMMENT ON TABLE bandit_model_parameters IS 'AI-1: Linear Thompson Sampling model parameters per arm';
COMMENT ON TABLE learning_insights IS 'AI-1: Generated insights from decision outcome analysis';

COMMENT ON COLUMN context_decisions.user_context IS 'User-specific context: energy, urgency, expertise, communication pref, cognitive load';
COMMENT ON COLUMN context_decisions.temporal_context IS 'Time-based context: time of day, day of week, work vs personal, deadlines';
COMMENT ON COLUMN context_decisions.environmental_context IS 'System context: load, workload, notifications, collaboration';
COMMENT ON COLUMN context_decisions.historical_context IS 'Historical context: success rate, stability, trajectory, sensitivity';
COMMENT ON COLUMN bandit_model_parameters.theta_mean IS 'Mean of posterior distribution over linear parameters';
COMMENT ON COLUMN bandit_model_parameters.theta_precision_matrix IS 'Precision matrix (inverse covariance) flattened row-major';
