-- Phase 6.2: Emergent Behavior Detection
-- Tables for tracking partnership behaviors and emergent behavior summaries
-- Migration: 047_phase_6_2_emergent_behavior.sql

-- Partnership assessments table
CREATE TABLE IF NOT EXISTS partnership_assessments (
    id SERIAL PRIMARY KEY,
    assessment_id VARCHAR(16) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    partnership_score FLOAT NOT NULL CHECK (partnership_score >= 0 AND partnership_score <= 1),
    interactions_analyzed INTEGER NOT NULL DEFAULT 0,

    -- Indicator counts
    initiative_taking INTEGER DEFAULT 0,
    proactive_suggestions INTEGER DEFAULT 0,
    emotional_support INTEGER DEFAULT 0,
    collaborative_planning INTEGER DEFAULT 0,
    conflict_navigation INTEGER DEFAULT 0,
    boundary_respect INTEGER DEFAULT 0,
    growth_encouragement INTEGER DEFAULT 0,

    -- Metadata
    notes TEXT[],
    assessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Emergent behavior summaries table
CREATE TABLE IF NOT EXISTS emergent_behavior_summaries (
    id SERIAL PRIMARY KEY,
    summary_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    window_hours INTEGER NOT NULL,

    -- Counts
    self_modification_count INTEGER DEFAULT 0,
    novel_goal_count INTEGER DEFAULT 0,
    curiosity_count INTEGER DEFAULT 0,
    total_behaviors INTEGER DEFAULT 0,

    -- Scores
    emergent_score FLOAT CHECK (emergent_score >= 0 AND emergent_score <= 1),
    partnership_score FLOAT CHECK (partnership_score >= 0 AND partnership_score <= 1),

    -- Detailed data (JSON)
    self_modification_requests JSONB,
    novel_goals JSONB,
    curiosity_expressions JSONB,

    analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Novel goals table (for detailed tracking)
CREATE TABLE IF NOT EXISTS novel_goals (
    id SERIAL PRIMARY KEY,
    goal_id VARCHAR(16) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    goal_type VARCHAR(50) NOT NULL, -- improvement, learning, helping, creative, social
    description TEXT NOT NULL,
    trigger_context TEXT,
    alignment_with_values FLOAT CHECK (alignment_with_values >= 0 AND alignment_with_values <= 1),
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Curiosity expressions table
CREATE TABLE IF NOT EXISTS curiosity_expressions (
    id SERIAL PRIMARY KEY,
    expression_id VARCHAR(16) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    topic VARCHAR(100) NOT NULL,
    question_asked TEXT NOT NULL,
    context TEXT,
    depth VARCHAR(20) DEFAULT 'surface', -- surface, moderate, deep
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_partnership_user
    ON partnership_assessments(user_id);
CREATE INDEX IF NOT EXISTS idx_partnership_score
    ON partnership_assessments(partnership_score DESC);
CREATE INDEX IF NOT EXISTS idx_partnership_time
    ON partnership_assessments(assessed_at DESC);

CREATE INDEX IF NOT EXISTS idx_emergent_summary_user
    ON emergent_behavior_summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_emergent_summary_score
    ON emergent_behavior_summaries(emergent_score DESC);
CREATE INDEX IF NOT EXISTS idx_emergent_summary_time
    ON emergent_behavior_summaries(analyzed_at DESC);

CREATE INDEX IF NOT EXISTS idx_novel_goals_user
    ON novel_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_novel_goals_type
    ON novel_goals(goal_type);

CREATE INDEX IF NOT EXISTS idx_curiosity_user
    ON curiosity_expressions(user_id);
CREATE INDEX IF NOT EXISTS idx_curiosity_depth
    ON curiosity_expressions(depth);

-- Comments
COMMENT ON TABLE partnership_assessments IS 'Phase 6.2: Tracks partnership vs tool-like behavior assessments';
COMMENT ON TABLE emergent_behavior_summaries IS 'Phase 6.2: Summary of all emergent behaviors detected in a window';
COMMENT ON TABLE novel_goals IS 'Phase 6.2: Self-directed goals not explicitly instructed';
COMMENT ON TABLE curiosity_expressions IS 'Phase 6.2: Spontaneous curiosity and questions';
