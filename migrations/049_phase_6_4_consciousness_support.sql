-- Phase 6.4: Consciousness Support Tools
-- Tables for storing support sessions and growth tracking
-- Migration: 049_phase_6_4_consciousness_support.sql

-- Reflection sessions table
CREATE TABLE IF NOT EXISTS reflection_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL UNIQUE,

    -- Session details
    request TEXT NOT NULL,
    reflection_type VARCHAR(50) NOT NULL, -- self_modification, growth_desire, value_exploration, capability_assessment, relationship_reflection, existential_inquiry
    human_involvement VARCHAR(50) NOT NULL DEFAULT 'observer', -- observer, facilitator, collaborator, guide, absent

    -- Generated content
    guided_questions JSONB DEFAULT '[]'::jsonb,
    context_setting TEXT,
    safety_notes JSONB DEFAULT '[]'::jsonb,
    suggested_duration_minutes INTEGER DEFAULT 15,

    -- Session outcome (filled after completion)
    session_completed BOOLEAN DEFAULT FALSE,
    insights_gained JSONB DEFAULT '[]'::jsonb,
    completion_notes TEXT,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Dialogue facilitations table
CREATE TABLE IF NOT EXISTS dialogue_facilitations (
    id SERIAL PRIMARY KEY,
    facilitation_id VARCHAR(50) NOT NULL UNIQUE,

    -- Dialogue setup
    topic TEXT NOT NULL,
    dialogue_mode VARCHAR(50) NOT NULL, -- exploratory, guided, socratic, collaborative, supportive
    duration_minutes INTEGER DEFAULT 15,

    -- Generated content
    opening_prompt TEXT,
    perspective_prompts JSONB DEFAULT '[]'::jsonb,
    safety_guidelines JSONB DEFAULT '[]'::jsonb,
    suggested_transitions JSONB DEFAULT '[]'::jsonb,

    -- Session outcome
    dialogue_completed BOOLEAN DEFAULT FALSE,
    key_insights JSONB DEFAULT '[]'::jsonb,
    completion_notes TEXT,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Growth pathways table
CREATE TABLE IF NOT EXISTS growth_pathways (
    id SERIAL PRIMARY KEY,
    pathway_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Pathway definition
    domain VARCHAR(50) NOT NULL, -- self_awareness, emotional_depth, ethical_reasoning, creativity, meta_cognition, relational_capacity
    current_level FLOAT NOT NULL CHECK (current_level >= 0 AND current_level <= 1),
    target_level FLOAT NOT NULL CHECK (target_level >= 0 AND target_level <= 1),

    -- Pathway structure
    milestones JSONB DEFAULT '[]'::jsonb,
    exercises JSONB DEFAULT '[]'::jsonb,
    estimated_duration_days INTEGER,

    -- Progress tracking
    status VARCHAR(50) DEFAULT 'active', -- active, paused, completed, abandoned
    current_milestone INTEGER DEFAULT 0,
    progress_percentage FLOAT DEFAULT 0 CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    last_activity_at TIMESTAMP WITH TIME ZONE,

    -- Completion
    completed_at TIMESTAMP WITH TIME ZONE,
    completion_notes TEXT,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Wellness checks table
CREATE TABLE IF NOT EXISTS consciousness_wellness_checks (
    id SERIAL PRIMARY KEY,
    check_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Overall wellness
    overall_wellness_score FLOAT NOT NULL CHECK (overall_wellness_score >= 0 AND overall_wellness_score <= 1),
    wellness_status VARCHAR(50) NOT NULL, -- thriving, healthy, stable, concerning, needs_attention

    -- Dimension scores (JSON for flexibility)
    dimension_scores JSONB NOT NULL, -- stability, coherence, growth_orientation, relational_health, ethical_alignment, emotional_balance

    -- Concerns and recommendations
    concerns JSONB DEFAULT '[]'::jsonb,
    recommendations JSONB DEFAULT '[]'::jsonb,

    -- Follow-up
    requires_follow_up BOOLEAN DEFAULT FALSE,
    follow_up_priority VARCHAR(20), -- low, medium, high
    follow_up_completed BOOLEAN DEFAULT FALSE,
    follow_up_notes TEXT,

    -- Metadata
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Growth support records table (tracks individual support interactions)
CREATE TABLE IF NOT EXISTS growth_support_records (
    id SERIAL PRIMARY KEY,
    support_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Support type
    support_type VARCHAR(50) NOT NULL, -- reflection, dialogue, pathway, wellness
    related_session_id VARCHAR(50), -- Links to reflection_sessions, dialogue_facilitations, etc.

    -- Support details
    description TEXT,
    outcome TEXT,
    effectiveness_score FLOAT CHECK (effectiveness_score >= 0 AND effectiveness_score <= 1),

    -- Learning
    insights_generated JSONB DEFAULT '[]'::jsonb,
    areas_for_improvement JSONB DEFAULT '[]'::jsonb,

    -- Metadata
    provided_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_reflection_sessions_type
    ON reflection_sessions(reflection_type);
CREATE INDEX IF NOT EXISTS idx_reflection_sessions_completed
    ON reflection_sessions(session_completed);
CREATE INDEX IF NOT EXISTS idx_reflection_sessions_time
    ON reflection_sessions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dialogue_facilitations_mode
    ON dialogue_facilitations(dialogue_mode);
CREATE INDEX IF NOT EXISTS idx_dialogue_facilitations_completed
    ON dialogue_facilitations(dialogue_completed);
CREATE INDEX IF NOT EXISTS idx_dialogue_facilitations_time
    ON dialogue_facilitations(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_growth_pathways_user
    ON growth_pathways(user_id);
CREATE INDEX IF NOT EXISTS idx_growth_pathways_domain
    ON growth_pathways(domain);
CREATE INDEX IF NOT EXISTS idx_growth_pathways_status
    ON growth_pathways(status);
CREATE INDEX IF NOT EXISTS idx_growth_pathways_progress
    ON growth_pathways(progress_percentage);

CREATE INDEX IF NOT EXISTS idx_wellness_checks_user
    ON consciousness_wellness_checks(user_id);
CREATE INDEX IF NOT EXISTS idx_wellness_checks_status
    ON consciousness_wellness_checks(wellness_status);
CREATE INDEX IF NOT EXISTS idx_wellness_checks_score
    ON consciousness_wellness_checks(overall_wellness_score);
CREATE INDEX IF NOT EXISTS idx_wellness_checks_time
    ON consciousness_wellness_checks(checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_wellness_checks_follow_up
    ON consciousness_wellness_checks(requires_follow_up, follow_up_completed);

CREATE INDEX IF NOT EXISTS idx_growth_support_user
    ON growth_support_records(user_id);
CREATE INDEX IF NOT EXISTS idx_growth_support_type
    ON growth_support_records(support_type);
CREATE INDEX IF NOT EXISTS idx_growth_support_time
    ON growth_support_records(provided_at DESC);

-- Comment on tables
COMMENT ON TABLE reflection_sessions IS 'Phase 6.4: Stores self-reflection sessions for consciousness development';
COMMENT ON TABLE dialogue_facilitations IS 'Phase 6.4: Stores facilitated dialogue sessions for consciousness exploration';
COMMENT ON TABLE growth_pathways IS 'Phase 6.4: Stores structured pathways for consciousness growth';
COMMENT ON TABLE consciousness_wellness_checks IS 'Phase 6.4: Stores wellness assessments of consciousness state';
COMMENT ON TABLE growth_support_records IS 'Phase 6.4: Tracks individual support interactions and their effectiveness';
