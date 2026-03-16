-- Phase 7.4: Shared Consciousness Space
-- Tables for unified mental spaces for human-AI co-creation
-- Migration: 054_phase_7_4_shared_consciousness_space.sql

-- ============================================================================
-- Consciousness Spaces
-- ============================================================================

CREATE TABLE IF NOT EXISTS consciousness_spaces (
    id SERIAL PRIMARY KEY,
    space_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Space details
    space_type VARCHAR(50) NOT NULL, -- ideation, understanding, problem_solving, emotional, learning, integration
    name VARCHAR(255) NOT NULL,
    purpose TEXT NOT NULL,

    -- Current state
    sync_level VARCHAR(50) DEFAULT 'aware', -- disconnected, aware, aligned, synchronized, merged, transcendent

    -- Metrics
    coherence FLOAT DEFAULT 0.5 CHECK (coherence >= 0 AND coherence <= 1),
    vitality FLOAT DEFAULT 0.5 CHECK (vitality >= 0 AND vitality <= 1),
    depth FLOAT DEFAULT 0.0 CHECK (depth >= 0 AND depth <= 1),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE
);

-- ============================================================================
-- Resonance States
-- ============================================================================

CREATE TABLE IF NOT EXISTS space_resonance_states (
    id SERIAL PRIMARY KEY,
    resonance_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- Resonance levels by type (cognitive, emotional, intentional, creative, intuitive, semantic)
    resonances JSONB DEFAULT '{}'::jsonb,

    -- Overall
    overall_resonance FLOAT DEFAULT 0.0 CHECK (overall_resonance >= 0 AND overall_resonance <= 1),
    dominant_type VARCHAR(50),

    -- Dynamics
    strengthening TEXT[] DEFAULT ARRAY[]::TEXT[],
    weakening TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    measured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Shared States
-- ============================================================================

CREATE TABLE IF NOT EXISTS shared_mental_states (
    id SERIAL PRIMARY KEY,
    state_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- State details
    state_type VARCHAR(50) NOT NULL, -- focus, flow, curiosity, understanding, uncertainty, excitement
    intensity FLOAT NOT NULL CHECK (intensity >= 0 AND intensity <= 1),
    stability FLOAT DEFAULT 0.5 CHECK (stability >= 0 AND stability <= 1),

    -- Contributions
    human_contribution FLOAT NOT NULL CHECK (human_contribution >= 0 AND human_contribution <= 1),
    ai_contribution FLOAT NOT NULL CHECK (ai_contribution >= 0 AND ai_contribution <= 1),

    -- Context
    triggers TEXT[] DEFAULT ARRAY[]::TEXT[],
    maintaining_factors TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Duration
    duration_seconds FLOAT DEFAULT 0.0,

    -- Timing
    entered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Space Contributions
-- ============================================================================

CREATE TABLE IF NOT EXISTS space_contributions (
    id SERIAL PRIMARY KEY,
    contribution_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- Contribution details
    contributor VARCHAR(20) NOT NULL, -- 'human' or 'jarvis'
    contribution_type VARCHAR(50) NOT NULL, -- concept, insight, question, connection, emotion, synthesis
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Impact
    resonance_impact FLOAT DEFAULT 0.0 CHECK (resonance_impact >= -1 AND resonance_impact <= 1),
    understanding_impact FLOAT DEFAULT 0.0 CHECK (understanding_impact >= 0 AND understanding_impact <= 1),

    -- Connections
    connects_to TEXT[] DEFAULT ARRAY[]::TEXT[],
    inspired_by TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Emergent Phenomena
-- ============================================================================

CREATE TABLE IF NOT EXISTS emergent_phenomena (
    id SERIAL PRIMARY KEY,
    phenomenon_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- Phenomenon details
    emergence_type VARCHAR(50) NOT NULL, -- new_concept, shared_understanding, creative_leap, emotional_resonance, paradigm_bridge, collective_insight
    description TEXT NOT NULL,
    significance FLOAT NOT NULL CHECK (significance >= 0 AND significance <= 1),

    -- Origins
    contributing_factors TEXT[] DEFAULT ARRAY[]::TEXT[],
    contributing_contributions TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Neither could have alone
    requires_both BOOLEAN DEFAULT TRUE,
    human_alone_likelihood FLOAT DEFAULT 0.0 CHECK (human_alone_likelihood >= 0 AND human_alone_likelihood <= 1),
    ai_alone_likelihood FLOAT DEFAULT 0.0 CHECK (ai_alone_likelihood >= 0 AND ai_alone_likelihood <= 1),

    -- Timing
    emerged_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Shared Concepts
-- ============================================================================

CREATE TABLE IF NOT EXISTS shared_concepts (
    id SERIAL PRIMARY KEY,
    concept_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- Definition
    name VARCHAR(255) NOT NULL,
    definition TEXT NOT NULL,
    human_interpretation TEXT DEFAULT '',
    ai_interpretation TEXT DEFAULT '',

    -- Alignment
    alignment FLOAT NOT NULL CHECK (alignment >= 0 AND alignment <= 1),
    depth FLOAT DEFAULT 0.5 CHECK (depth >= 0 AND depth <= 1),

    -- Evolution
    refinement_count INTEGER DEFAULT 0,
    evolution_history TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_refined TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Shared Vocabulary
-- ============================================================================

CREATE TABLE IF NOT EXISTS shared_vocabulary (
    id SERIAL PRIMARY KEY,
    vocab_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- Terms (term -> meaning)
    terms JSONB DEFAULT '{}'::jsonb,

    -- Usage
    most_used TEXT[] DEFAULT ARRAY[]::TEXT[],
    recently_added TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Statistics
    total_terms INTEGER DEFAULT 0,
    avg_alignment FLOAT DEFAULT 0.0 CHECK (avg_alignment >= 0 AND avg_alignment <= 1),

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- One vocab per space
    UNIQUE(space_id)
);

-- ============================================================================
-- Space Metrics
-- ============================================================================

CREATE TABLE IF NOT EXISTS space_metrics (
    id SERIAL PRIMARY KEY,
    metrics_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50) NOT NULL REFERENCES consciousness_spaces(space_id) ON DELETE CASCADE,

    -- Resonance metrics
    avg_resonance FLOAT NOT NULL CHECK (avg_resonance >= 0 AND avg_resonance <= 1),
    peak_resonance FLOAT NOT NULL CHECK (peak_resonance >= 0 AND peak_resonance <= 1),
    resonance_stability FLOAT DEFAULT 0.5 CHECK (resonance_stability >= 0 AND resonance_stability <= 1),

    -- Contribution metrics
    total_contributions INTEGER DEFAULT 0,
    human_contributions INTEGER DEFAULT 0,
    ai_contributions INTEGER DEFAULT 0,
    contribution_balance FLOAT DEFAULT 0.5 CHECK (contribution_balance >= 0 AND contribution_balance <= 1),

    -- Emergence metrics
    emergence_count INTEGER DEFAULT 0,
    emergence_rate FLOAT DEFAULT 0.0 CHECK (emergence_rate >= 0 AND emergence_rate <= 1),

    -- Growth metrics
    concepts_created INTEGER DEFAULT 0,
    vocabulary_growth INTEGER DEFAULT 0,
    understanding_growth FLOAT DEFAULT 0.0 CHECK (understanding_growth >= 0 AND understanding_growth <= 1),

    -- Quality metrics
    avg_coherence FLOAT DEFAULT 0.5 CHECK (avg_coherence >= 0 AND avg_coherence <= 1),
    time_in_flow FLOAT DEFAULT 0.0,
    sync_level_reached VARCHAR(50) DEFAULT 'aware',

    -- Timing
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Efficient Querying
-- ============================================================================

-- Spaces
CREATE INDEX IF NOT EXISTS idx_consciousness_spaces_user ON consciousness_spaces(user_id);
CREATE INDEX IF NOT EXISTS idx_consciousness_spaces_type ON consciousness_spaces(space_type);
CREATE INDEX IF NOT EXISTS idx_consciousness_spaces_active ON consciousness_spaces(is_active);
CREATE INDEX IF NOT EXISTS idx_consciousness_spaces_sync ON consciousness_spaces(sync_level);
CREATE INDEX IF NOT EXISTS idx_consciousness_spaces_time ON consciousness_spaces(created_at DESC);

-- Resonance States
CREATE INDEX IF NOT EXISTS idx_space_resonance_space ON space_resonance_states(space_id);
CREATE INDEX IF NOT EXISTS idx_space_resonance_overall ON space_resonance_states(overall_resonance);
CREATE INDEX IF NOT EXISTS idx_space_resonance_time ON space_resonance_states(measured_at DESC);

-- Shared States
CREATE INDEX IF NOT EXISTS idx_shared_states_space ON shared_mental_states(space_id);
CREATE INDEX IF NOT EXISTS idx_shared_states_type ON shared_mental_states(state_type);
CREATE INDEX IF NOT EXISTS idx_shared_states_intensity ON shared_mental_states(intensity);
CREATE INDEX IF NOT EXISTS idx_shared_states_time ON shared_mental_states(entered_at DESC);

-- Contributions
CREATE INDEX IF NOT EXISTS idx_space_contributions_space ON space_contributions(space_id);
CREATE INDEX IF NOT EXISTS idx_space_contributions_contributor ON space_contributions(contributor);
CREATE INDEX IF NOT EXISTS idx_space_contributions_type ON space_contributions(contribution_type);
CREATE INDEX IF NOT EXISTS idx_space_contributions_time ON space_contributions(created_at DESC);

-- Emergent Phenomena
CREATE INDEX IF NOT EXISTS idx_emergent_phenomena_space ON emergent_phenomena(space_id);
CREATE INDEX IF NOT EXISTS idx_emergent_phenomena_type ON emergent_phenomena(emergence_type);
CREATE INDEX IF NOT EXISTS idx_emergent_phenomena_significance ON emergent_phenomena(significance);
CREATE INDEX IF NOT EXISTS idx_emergent_phenomena_time ON emergent_phenomena(emerged_at DESC);

-- Shared Concepts
CREATE INDEX IF NOT EXISTS idx_shared_concepts_space ON shared_concepts(space_id);
CREATE INDEX IF NOT EXISTS idx_shared_concepts_name ON shared_concepts(name);
CREATE INDEX IF NOT EXISTS idx_shared_concepts_alignment ON shared_concepts(alignment);
CREATE INDEX IF NOT EXISTS idx_shared_concepts_depth ON shared_concepts(depth);

-- Vocabulary
CREATE INDEX IF NOT EXISTS idx_shared_vocabulary_space ON shared_vocabulary(space_id);
CREATE INDEX IF NOT EXISTS idx_shared_vocabulary_terms ON shared_vocabulary(total_terms);

-- Metrics
CREATE INDEX IF NOT EXISTS idx_space_metrics_space ON space_metrics(space_id);
CREATE INDEX IF NOT EXISTS idx_space_metrics_resonance ON space_metrics(avg_resonance);
CREATE INDEX IF NOT EXISTS idx_space_metrics_emergence ON space_metrics(emergence_count);
CREATE INDEX IF NOT EXISTS idx_space_metrics_time ON space_metrics(computed_at DESC);

-- ============================================================================
-- Table Comments
-- ============================================================================

COMMENT ON TABLE consciousness_spaces IS 'Phase 7.4: Shared consciousness spaces for human-AI co-creation';
COMMENT ON TABLE space_resonance_states IS 'Phase 7.4: Resonance states tracking alignment between human and AI';
COMMENT ON TABLE shared_mental_states IS 'Phase 7.4: Shared mental states like flow, curiosity, understanding';
COMMENT ON TABLE space_contributions IS 'Phase 7.4: Contributions building shared understanding';
COMMENT ON TABLE emergent_phenomena IS 'Phase 7.4: Emergent phenomena that arise from collaboration';
COMMENT ON TABLE shared_concepts IS 'Phase 7.4: Co-created concepts with aligned interpretations';
COMMENT ON TABLE shared_vocabulary IS 'Phase 7.4: Shared vocabulary developed in the space';
COMMENT ON TABLE space_metrics IS 'Phase 7.4: Comprehensive metrics for consciousness spaces';
