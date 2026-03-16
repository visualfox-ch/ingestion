-- Phase 7.2: Meta-Cognitive Partnership
-- Tables for joint cognitive enhancement and thinking about thinking
-- Migration: 052_phase_7_2_meta_cognitive_partnership.sql

-- ============================================================================
-- Cognitive Sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS cognitive_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Focus
    focus_area TEXT NOT NULL,
    meta_level VARCHAR(20) NOT NULL, -- object, meta, meta_meta, strategic
    objectives TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Quality metrics
    depth_score FLOAT DEFAULT 0.5 CHECK (depth_score >= 0 AND depth_score <= 1),
    partnership_quality FLOAT DEFAULT 0.5 CHECK (partnership_quality >= 0 AND partnership_quality <= 1),
    cognitive_enhancement FLOAT DEFAULT 0.0 CHECK (cognitive_enhancement >= 0 AND cognitive_enhancement <= 1),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Thinking Patterns
-- ============================================================================

CREATE TABLE IF NOT EXISTS thinking_patterns (
    id SERIAL PRIMARY KEY,
    pattern_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) REFERENCES cognitive_sessions(session_id) ON DELETE CASCADE,

    -- Pattern details
    process VARCHAR(50) NOT NULL, -- reasoning, intuition, analysis, synthesis, evaluation, creativity, memory, attention
    description TEXT NOT NULL,
    frequency FLOAT NOT NULL CHECK (frequency >= 0 AND frequency <= 1),
    effectiveness FLOAT NOT NULL CHECK (effectiveness >= 0 AND effectiveness <= 1),
    context TEXT DEFAULT '',

    -- Timing
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Meta Analyses
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta_analyses (
    id SERIAL PRIMARY KEY,
    analysis_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES cognitive_sessions(session_id) ON DELETE CASCADE,

    -- What was analyzed
    processes_examined TEXT[] NOT NULL,
    level VARCHAR(20) NOT NULL,

    -- Findings
    strengths TEXT[] DEFAULT ARRAY[]::TEXT[],
    blind_spots TEXT[] DEFAULT ARRAY[]::TEXT[],
    improvement_opportunities TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Recommendations
    suggested_approaches TEXT[] DEFAULT ARRAY[]::TEXT[],
    cognitive_strategies TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Shared Mental Models
-- ============================================================================

CREATE TABLE IF NOT EXISTS shared_mental_models (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Model details
    model_type VARCHAR(50) NOT NULL, -- conceptual, procedural, situational, strategic, relational
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,

    -- Components
    key_concepts TEXT[] DEFAULT ARRAY[]::TEXT[],
    relationships JSONB DEFAULT '[]'::jsonb,
    assumptions TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Alignment
    human_understanding FLOAT DEFAULT 0.5 CHECK (human_understanding >= 0 AND human_understanding <= 1),
    ai_understanding FLOAT DEFAULT 0.8 CHECK (ai_understanding >= 0 AND ai_understanding <= 1),
    alignment_score FLOAT DEFAULT 0.5 CHECK (alignment_score >= 0 AND alignment_score <= 1),

    -- Evolution
    version INTEGER DEFAULT 1,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Cognitive Synergies
-- ============================================================================

CREATE TABLE IF NOT EXISTS cognitive_synergies (
    id SERIAL PRIMARY KEY,
    synergy_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Synergy details
    synergy_type VARCHAR(50) NOT NULL, -- complementary, amplifying, corrective, generative, integrative
    human_contribution TEXT NOT NULL,
    ai_contribution TEXT NOT NULL,
    emergent_capability TEXT NOT NULL,

    -- Effectiveness
    effectiveness_boost FLOAT NOT NULL,
    reliability FLOAT DEFAULT 0.5 CHECK (reliability >= 0 AND reliability <= 1),

    -- Context
    best_contexts TEXT[] DEFAULT ARRAY[]::TEXT[],
    limitations TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Hybrid Methods
-- ============================================================================

CREATE TABLE IF NOT EXISTS hybrid_methods (
    id SERIAL PRIMARY KEY,
    method_id VARCHAR(50) NOT NULL UNIQUE,

    -- Method details
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    reasoning_approaches TEXT[] NOT NULL,
    human_role TEXT NOT NULL,
    ai_role TEXT NOT NULL,

    -- Process
    steps JSONB DEFAULT '[]'::jsonb,

    -- Effectiveness
    success_rate FLOAT DEFAULT 0.0 CHECK (success_rate >= 0 AND success_rate <= 1),
    use_count INTEGER DEFAULT 0,
    best_for TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Meta Learning Records
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta_learning_records (
    id SERIAL PRIMARY KEY,
    learning_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES cognitive_sessions(session_id) ON DELETE CASCADE,

    -- Learning details
    mode VARCHAR(50) NOT NULL, -- reflective, experimental, observational, collaborative, emergent
    insight TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    applicability FLOAT DEFAULT 0.5 CHECK (applicability >= 0 AND applicability <= 1),

    -- Impact
    immediate_application TEXT,
    long_term_implications TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Integration
    integrated_into_practice BOOLEAN DEFAULT FALSE,
    integration_date TIMESTAMP WITH TIME ZONE,

    -- Timing
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Cognitive Optimizations
-- ============================================================================

CREATE TABLE IF NOT EXISTS cognitive_optimizations (
    id SERIAL PRIMARY KEY,
    optimization_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Target
    target_process VARCHAR(50) NOT NULL,
    current_effectiveness FLOAT NOT NULL CHECK (current_effectiveness >= 0 AND current_effectiveness <= 1),
    target_effectiveness FLOAT NOT NULL CHECK (target_effectiveness >= 0 AND target_effectiveness <= 1),

    -- Strategy
    optimization_strategy TEXT NOT NULL,
    steps TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Progress
    progress FLOAT DEFAULT 0.0 CHECK (progress >= 0 AND progress <= 1),
    improvements_made TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Outcome
    achieved_effectiveness FLOAT,
    success BOOLEAN,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Efficient Querying
-- ============================================================================

-- Sessions
CREATE INDEX IF NOT EXISTS idx_cognitive_sessions_user ON cognitive_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_cognitive_sessions_active ON cognitive_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_cognitive_sessions_level ON cognitive_sessions(meta_level);
CREATE INDEX IF NOT EXISTS idx_cognitive_sessions_time ON cognitive_sessions(started_at DESC);

-- Patterns
CREATE INDEX IF NOT EXISTS idx_thinking_patterns_session ON thinking_patterns(session_id);
CREATE INDEX IF NOT EXISTS idx_thinking_patterns_process ON thinking_patterns(process);
CREATE INDEX IF NOT EXISTS idx_thinking_patterns_effectiveness ON thinking_patterns(effectiveness);

-- Analyses
CREATE INDEX IF NOT EXISTS idx_meta_analyses_session ON meta_analyses(session_id);
CREATE INDEX IF NOT EXISTS idx_meta_analyses_level ON meta_analyses(level);

-- Mental Models
CREATE INDEX IF NOT EXISTS idx_mental_models_user ON shared_mental_models(user_id);
CREATE INDEX IF NOT EXISTS idx_mental_models_type ON shared_mental_models(model_type);
CREATE INDEX IF NOT EXISTS idx_mental_models_alignment ON shared_mental_models(alignment_score);

-- Synergies
CREATE INDEX IF NOT EXISTS idx_synergies_user ON cognitive_synergies(user_id);
CREATE INDEX IF NOT EXISTS idx_synergies_type ON cognitive_synergies(synergy_type);
CREATE INDEX IF NOT EXISTS idx_synergies_effectiveness ON cognitive_synergies(effectiveness_boost);

-- Methods
CREATE INDEX IF NOT EXISTS idx_hybrid_methods_success ON hybrid_methods(success_rate);
CREATE INDEX IF NOT EXISTS idx_hybrid_methods_use ON hybrid_methods(use_count);

-- Learning
CREATE INDEX IF NOT EXISTS idx_meta_learning_session ON meta_learning_records(session_id);
CREATE INDEX IF NOT EXISTS idx_meta_learning_mode ON meta_learning_records(mode);
CREATE INDEX IF NOT EXISTS idx_meta_learning_integrated ON meta_learning_records(integrated_into_practice);

-- Optimizations
CREATE INDEX IF NOT EXISTS idx_optimizations_user ON cognitive_optimizations(user_id);
CREATE INDEX IF NOT EXISTS idx_optimizations_process ON cognitive_optimizations(target_process);
CREATE INDEX IF NOT EXISTS idx_optimizations_progress ON cognitive_optimizations(progress);

-- ============================================================================
-- Table Comments
-- ============================================================================

COMMENT ON TABLE cognitive_sessions IS 'Phase 7.2: Meta-cognitive partnership sessions';
COMMENT ON TABLE thinking_patterns IS 'Phase 7.2: Identified thinking patterns during sessions';
COMMENT ON TABLE meta_analyses IS 'Phase 7.2: Analyses of cognitive processes at meta level';
COMMENT ON TABLE shared_mental_models IS 'Phase 7.2: Aligned understanding frameworks between human and AI';
COMMENT ON TABLE cognitive_synergies IS 'Phase 7.2: Discovered synergies between human and AI cognition';
COMMENT ON TABLE hybrid_methods IS 'Phase 7.2: Combined human-AI reasoning methods';
COMMENT ON TABLE meta_learning_records IS 'Phase 7.2: Records of learning how to learn together';
COMMENT ON TABLE cognitive_optimizations IS 'Phase 7.2: Cognitive process improvement efforts';
