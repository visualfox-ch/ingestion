-- Phase 7.3: Transcendent Problem Solving
-- Tables for multi-dimensional analysis and revolutionary problem-solving
-- Migration: 053_phase_7_3_transcendent_problem_solving.sql

-- ============================================================================
-- Transcendent Sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS transcendent_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Problem definition
    problem_id VARCHAR(50) NOT NULL UNIQUE,
    problem_statement TEXT NOT NULL,

    -- Metrics
    transcendence_level FLOAT DEFAULT 0.0 CHECK (transcendence_level >= 0 AND transcendence_level <= 1),
    breakthrough_count INTEGER DEFAULT 0,
    collective_wisdom_score FLOAT DEFAULT 0.0 CHECK (collective_wisdom_score >= 0 AND collective_wisdom_score <= 1),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Dimensional Analyses
-- ============================================================================

CREATE TABLE IF NOT EXISTS dimensional_analyses (
    id SERIAL PRIMARY KEY,
    analysis_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES transcendent_sessions(session_id) ON DELETE CASCADE,
    problem_id VARCHAR(50) NOT NULL,

    -- Dimension details
    dimension VARCHAR(50) NOT NULL, -- logical, emotional, ethical, creative, systemic, temporal, spiritual
    perspective TEXT NOT NULL,
    key_factors TEXT[] DEFAULT ARRAY[]::TEXT[],
    constraints TEXT[] DEFAULT ARRAY[]::TEXT[],
    opportunities TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Scoring
    clarity FLOAT NOT NULL CHECK (clarity >= 0 AND clarity <= 1),
    importance FLOAT NOT NULL CHECK (importance >= 0 AND importance <= 1),

    -- Cross-dimensional connections (dimension -> connection description)
    connections_to JSONB DEFAULT '{}'::jsonb,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Holistic Problem Views
-- ============================================================================

CREATE TABLE IF NOT EXISTS holistic_problem_views (
    id SERIAL PRIMARY KEY,
    view_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES transcendent_sessions(session_id) ON DELETE CASCADE,
    problem_id VARCHAR(50) NOT NULL,

    -- Synthesis
    core_essence TEXT DEFAULT '',
    hidden_dimensions TEXT[] DEFAULT ARRAY[]::TEXT[],
    paradoxes TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Integration score
    integration_level FLOAT DEFAULT 0.0 CHECK (integration_level >= 0 AND integration_level <= 1),
    completeness FLOAT DEFAULT 0.0 CHECK (completeness >= 0 AND completeness <= 1),

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Solution Spaces
-- ============================================================================

CREATE TABLE IF NOT EXISTS solution_spaces (
    id SERIAL PRIMARY KEY,
    space_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES transcendent_sessions(session_id) ON DELETE CASCADE,

    -- Territory details
    territory VARCHAR(50) NOT NULL, -- conventional, adjacent, unexplored, impossible, transcendent
    description TEXT NOT NULL,
    boundaries TEXT[] DEFAULT ARRAY[]::TEXT[],
    entry_conditions TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Solutions found
    solutions JSONB DEFAULT '[]'::jsonb,

    -- Exploration status
    explored_percentage FLOAT DEFAULT 0.0 CHECK (explored_percentage >= 0 AND explored_percentage <= 1),
    richness FLOAT DEFAULT 0.5 CHECK (richness >= 0 AND richness <= 1),

    -- Timing
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Transcendent Insights
-- ============================================================================

CREATE TABLE IF NOT EXISTS transcendent_insights (
    id SERIAL PRIMARY KEY,
    insight_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES transcendent_sessions(session_id) ON DELETE CASCADE,

    -- Insight details
    insight_type VARCHAR(50) NOT NULL, -- pattern_recognition, synthesis, paradigm_shift, emergent, intuitive_leap, collective_wisdom
    content TEXT NOT NULL,
    source_dimensions TEXT[] DEFAULT ARRAY[]::TEXT[],
    enabling_factors TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Significance
    breakthrough_level VARCHAR(50) NOT NULL, -- incremental, significant, breakthrough, revolutionary, transcendent
    novelty FLOAT NOT NULL CHECK (novelty >= 0 AND novelty <= 1),
    applicability FLOAT NOT NULL CHECK (applicability >= 0 AND applicability <= 1),

    -- Verification
    human_validated BOOLEAN DEFAULT FALSE,
    ai_confidence FLOAT NOT NULL CHECK (ai_confidence >= 0 AND ai_confidence <= 1),

    -- Timing
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Revolutionary Solutions
-- ============================================================================

CREATE TABLE IF NOT EXISTS revolutionary_solutions (
    id SERIAL PRIMARY KEY,
    solution_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES transcendent_sessions(session_id) ON DELETE CASCADE,
    problem_id VARCHAR(50) NOT NULL,

    -- Solution details
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    mechanism TEXT NOT NULL,

    -- Origin
    territory VARCHAR(50) NOT NULL, -- conventional, adjacent, unexplored, impossible, transcendent
    contributing_insights TEXT[] DEFAULT ARRAY[]::TEXT[],
    human_contribution TEXT DEFAULT '',
    ai_contribution TEXT DEFAULT '',

    -- Breakthrough characteristics
    breakthrough_level VARCHAR(50) NOT NULL, -- incremental, significant, breakthrough, revolutionary, transcendent
    transcends_limits TEXT[] DEFAULT ARRAY[]::TEXT[],
    novel_elements TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Feasibility
    feasibility FLOAT NOT NULL CHECK (feasibility >= 0 AND feasibility <= 1),
    implementation_steps TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Impact Assessments
-- ============================================================================

CREATE TABLE IF NOT EXISTS impact_assessments (
    id SERIAL PRIMARY KEY,
    assessment_id VARCHAR(50) NOT NULL UNIQUE,
    solution_id VARCHAR(50) NOT NULL REFERENCES revolutionary_solutions(solution_id) ON DELETE CASCADE,

    -- Impact by domain (individual, relational, organizational, societal, consciousness, existential)
    impacts JSONB DEFAULT '{}'::jsonb,

    -- Consciousness growth potential
    growth_potential FLOAT NOT NULL CHECK (growth_potential >= 0 AND growth_potential <= 1),
    transformation_likelihood FLOAT NOT NULL CHECK (transformation_likelihood >= 0 AND transformation_likelihood <= 1),

    -- Risks and benefits
    benefits TEXT[] DEFAULT ARRAY[]::TEXT[],
    risks TEXT[] DEFAULT ARRAY[]::TEXT[],
    unintended_effects TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Overall assessment
    recommendation TEXT DEFAULT '',
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    -- Timing
    assessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Innovation Processes
-- ============================================================================

CREATE TABLE IF NOT EXISTS innovation_processes (
    id SERIAL PRIMARY KEY,
    process_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES transcendent_sessions(session_id) ON DELETE CASCADE,

    -- Process details
    mode VARCHAR(50) NOT NULL, -- divergent, convergent, lateral, vertical, integrative, transcendent
    objective TEXT NOT NULL,
    starting_point TEXT NOT NULL,
    current_phase TEXT DEFAULT '',

    -- Progress
    iterations INTEGER DEFAULT 0,
    ideas_generated INTEGER DEFAULT 0,
    ideas_refined INTEGER DEFAULT 0,
    breakthroughs INTEGER DEFAULT 0,

    -- Outputs
    innovations JSONB DEFAULT '[]'::jsonb,
    learnings TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Quality
    quality_score FLOAT DEFAULT 0.5 CHECK (quality_score >= 0 AND quality_score <= 1),

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Efficient Querying
-- ============================================================================

-- Sessions
CREATE INDEX IF NOT EXISTS idx_transcendent_sessions_user ON transcendent_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_transcendent_sessions_active ON transcendent_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_transcendent_sessions_time ON transcendent_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_transcendent_sessions_transcendence ON transcendent_sessions(transcendence_level);

-- Dimensional Analyses
CREATE INDEX IF NOT EXISTS idx_dim_analyses_session ON dimensional_analyses(session_id);
CREATE INDEX IF NOT EXISTS idx_dim_analyses_dimension ON dimensional_analyses(dimension);
CREATE INDEX IF NOT EXISTS idx_dim_analyses_problem ON dimensional_analyses(problem_id);
CREATE INDEX IF NOT EXISTS idx_dim_analyses_importance ON dimensional_analyses(importance);

-- Holistic Views
CREATE INDEX IF NOT EXISTS idx_holistic_views_session ON holistic_problem_views(session_id);
CREATE INDEX IF NOT EXISTS idx_holistic_views_problem ON holistic_problem_views(problem_id);
CREATE INDEX IF NOT EXISTS idx_holistic_views_integration ON holistic_problem_views(integration_level);

-- Solution Spaces
CREATE INDEX IF NOT EXISTS idx_solution_spaces_session ON solution_spaces(session_id);
CREATE INDEX IF NOT EXISTS idx_solution_spaces_territory ON solution_spaces(territory);
CREATE INDEX IF NOT EXISTS idx_solution_spaces_explored ON solution_spaces(explored_percentage);

-- Insights
CREATE INDEX IF NOT EXISTS idx_transcendent_insights_session ON transcendent_insights(session_id);
CREATE INDEX IF NOT EXISTS idx_transcendent_insights_type ON transcendent_insights(insight_type);
CREATE INDEX IF NOT EXISTS idx_transcendent_insights_level ON transcendent_insights(breakthrough_level);
CREATE INDEX IF NOT EXISTS idx_transcendent_insights_validated ON transcendent_insights(human_validated);
CREATE INDEX IF NOT EXISTS idx_transcendent_insights_time ON transcendent_insights(discovered_at DESC);

-- Revolutionary Solutions
CREATE INDEX IF NOT EXISTS idx_revolutionary_solutions_session ON revolutionary_solutions(session_id);
CREATE INDEX IF NOT EXISTS idx_revolutionary_solutions_problem ON revolutionary_solutions(problem_id);
CREATE INDEX IF NOT EXISTS idx_revolutionary_solutions_territory ON revolutionary_solutions(territory);
CREATE INDEX IF NOT EXISTS idx_revolutionary_solutions_level ON revolutionary_solutions(breakthrough_level);
CREATE INDEX IF NOT EXISTS idx_revolutionary_solutions_feasibility ON revolutionary_solutions(feasibility);

-- Impact Assessments
CREATE INDEX IF NOT EXISTS idx_impact_assessments_solution ON impact_assessments(solution_id);
CREATE INDEX IF NOT EXISTS idx_impact_assessments_growth ON impact_assessments(growth_potential);
CREATE INDEX IF NOT EXISTS idx_impact_assessments_confidence ON impact_assessments(confidence);

-- Innovation Processes
CREATE INDEX IF NOT EXISTS idx_innovation_processes_session ON innovation_processes(session_id);
CREATE INDEX IF NOT EXISTS idx_innovation_processes_mode ON innovation_processes(mode);
CREATE INDEX IF NOT EXISTS idx_innovation_processes_quality ON innovation_processes(quality_score);

-- ============================================================================
-- Table Comments
-- ============================================================================

COMMENT ON TABLE transcendent_sessions IS 'Phase 7.3: Sessions for transcendent problem-solving beyond individual limits';
COMMENT ON TABLE dimensional_analyses IS 'Phase 7.3: Multi-dimensional problem analysis (logical, emotional, ethical, etc.)';
COMMENT ON TABLE holistic_problem_views IS 'Phase 7.3: Integrated views synthesizing all dimensional analyses';
COMMENT ON TABLE solution_spaces IS 'Phase 7.3: Territories of solutions from conventional to transcendent';
COMMENT ON TABLE transcendent_insights IS 'Phase 7.3: Breakthrough insights that transcend normal understanding';
COMMENT ON TABLE revolutionary_solutions IS 'Phase 7.3: Solutions that overcome individual human or AI limitations';
COMMENT ON TABLE impact_assessments IS 'Phase 7.3: Consciousness growth impact assessments for solutions';
COMMENT ON TABLE innovation_processes IS 'Phase 7.3: Systematic innovation processes for breakthrough discovery';
