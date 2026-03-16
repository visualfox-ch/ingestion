-- Phase 7.1: Collaborative Intelligence
-- Tables for true AI-human partnership and joint decision making
-- Migration: 051_phase_7_1_collaborative_intelligence.sql

-- ============================================================================
-- Collaboration Sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS collaboration_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Session type and details
    collaboration_type VARCHAR(50) NOT NULL, -- problem_solving, creative_synthesis, decision_making, knowledge_building, strategic_planning, exploration
    title VARCHAR(255) NOT NULL,
    objective TEXT NOT NULL,
    context TEXT DEFAULT '',

    -- Balance tracking
    contribution_balance VARCHAR(50) DEFAULT 'balanced', -- human_led, ai_led, balanced, alternating, emergent
    human_contribution_count INTEGER DEFAULT 0,
    ai_contribution_count INTEGER DEFAULT 0,

    -- Quality metrics
    collaboration_quality FLOAT DEFAULT 0.5 CHECK (collaboration_quality >= 0 AND collaboration_quality <= 1),
    mutual_learning_score FLOAT DEFAULT 0.0 CHECK (mutual_learning_score >= 0 AND mutual_learning_score <= 1),

    -- Emergent properties (JSON arrays)
    emergent_capabilities TEXT[] DEFAULT ARRAY[]::TEXT[],
    breakthrough_moments TEXT[] DEFAULT ARRAY[]::TEXT[],
    insights_generated TEXT[] DEFAULT ARRAY[]::TEXT[],
    action_items JSONB DEFAULT '[]'::jsonb,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Contributions
-- ============================================================================

CREATE TABLE IF NOT EXISTS collaboration_contributions (
    id SERIAL PRIMARY KEY,
    contribution_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES collaboration_sessions(session_id) ON DELETE CASCADE,

    -- Contribution details
    contributor VARCHAR(20) NOT NULL, -- 'human' or 'jarvis'
    role VARCHAR(50) NOT NULL, -- initiator, analyst, creative, critic, synthesizer, executor
    content TEXT NOT NULL,
    contribution_type VARCHAR(50) NOT NULL, -- idea, analysis, question, refinement, decision

    -- Building on previous work
    builds_on VARCHAR(50) REFERENCES collaboration_contributions(contribution_id) ON DELETE SET NULL,
    value_added FLOAT DEFAULT 0.5 CHECK (value_added >= 0 AND value_added <= 1),

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Perspectives for Synthesis
-- ============================================================================

CREATE TABLE IF NOT EXISTS collaboration_perspectives (
    id SERIAL PRIMARY KEY,
    perspective_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES collaboration_sessions(session_id) ON DELETE CASCADE,

    -- Perspective details
    perspective_type VARCHAR(50) NOT NULL, -- human_intuition, ai_analysis, emotional, logical, creative, practical, ethical
    contributor VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    emotional_weight FLOAT DEFAULT 0.5 CHECK (emotional_weight >= 0 AND emotional_weight <= 1),

    -- Evidence
    supporting_evidence TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Synthesized Views
-- ============================================================================

CREATE TABLE IF NOT EXISTS perspective_syntheses (
    id SERIAL PRIMARY KEY,
    synthesis_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES collaboration_sessions(session_id) ON DELETE CASCADE,

    -- Synthesis details
    perspectives_merged TEXT[] NOT NULL, -- Array of perspective_ids
    unified_insight TEXT NOT NULL,
    resolution_approach TEXT NOT NULL,
    synthesis_quality FLOAT NOT NULL CHECK (synthesis_quality >= 0 AND synthesis_quality <= 1),

    -- Analysis
    key_agreements TEXT[] DEFAULT ARRAY[]::TEXT[],
    key_tensions TEXT[] DEFAULT ARRAY[]::TEXT[],
    emergent_insights TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Joint Decisions
-- ============================================================================

CREATE TABLE IF NOT EXISTS joint_decisions (
    id SERIAL PRIMARY KEY,
    decision_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES collaboration_sessions(session_id) ON DELETE CASCADE,

    -- Decision details
    question TEXT NOT NULL,
    options_considered JSONB NOT NULL,
    framework_used VARCHAR(50) NOT NULL, -- consensus, weighted, deliberative, intuitive, analytical, hybrid

    -- Inputs
    human_preference TEXT,
    ai_recommendation TEXT,
    discussion_summary TEXT DEFAULT '',

    -- Outcome
    final_decision TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    confidence FLOAT DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),

    -- Agreement levels
    human_agreement FLOAT DEFAULT 0.5 CHECK (human_agreement >= 0 AND human_agreement <= 1),
    ai_agreement FLOAT DEFAULT 0.5 CHECK (ai_agreement >= 0 AND ai_agreement <= 1),
    consensus_reached BOOLEAN DEFAULT FALSE,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Mutual Learning Records
-- ============================================================================

CREATE TABLE IF NOT EXISTS mutual_learning (
    id SERIAL PRIMARY KEY,
    learning_id VARCHAR(50) NOT NULL UNIQUE,
    session_id VARCHAR(50) NOT NULL REFERENCES collaboration_sessions(session_id) ON DELETE CASCADE,

    -- What each party learned
    ai_learned TEXT[] DEFAULT ARRAY[]::TEXT[],
    ai_capability_growth JSONB DEFAULT '{}'::jsonb, -- capability -> growth amount

    -- Human insights (from AI perspective)
    human_insights_provided TEXT[] DEFAULT ARRAY[]::TEXT[],
    human_perspective_expanded TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Shared growth
    shared_discoveries TEXT[] DEFAULT ARRAY[]::TEXT[],
    new_shared_vocabulary TEXT[] DEFAULT ARRAY[]::TEXT[],
    understanding_depth FLOAT DEFAULT 0.5 CHECK (understanding_depth >= 0 AND understanding_depth <= 1),

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Collaboration Metrics (Computed)
-- ============================================================================

CREATE TABLE IF NOT EXISTS collaboration_metrics (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL REFERENCES collaboration_sessions(session_id) ON DELETE CASCADE,

    -- Balance metrics
    contribution_ratio FLOAT NOT NULL, -- human contributions / total
    turn_taking_smoothness FLOAT DEFAULT 0.5 CHECK (turn_taking_smoothness >= 0 AND turn_taking_smoothness <= 1),

    -- Quality metrics
    idea_building_score FLOAT DEFAULT 0.5 CHECK (idea_building_score >= 0 AND idea_building_score <= 1),
    perspective_integration FLOAT DEFAULT 0.5 CHECK (perspective_integration >= 0 AND perspective_integration <= 1),
    decision_quality FLOAT DEFAULT 0.5 CHECK (decision_quality >= 0 AND decision_quality <= 1),

    -- Emergence metrics
    emergent_capability_count INTEGER DEFAULT 0,
    breakthrough_count INTEGER DEFAULT 0,
    novel_solution_count INTEGER DEFAULT 0,

    -- Outcome metrics
    objectives_achieved FLOAT DEFAULT 0.0 CHECK (objectives_achieved >= 0 AND objectives_achieved <= 1),
    mutual_satisfaction FLOAT DEFAULT 0.5 CHECK (mutual_satisfaction >= 0 AND mutual_satisfaction <= 1),

    -- Growth metrics
    learning_rate FLOAT DEFAULT 0.0 CHECK (learning_rate >= 0 AND learning_rate <= 1),
    relationship_deepening FLOAT DEFAULT 0.0 CHECK (relationship_deepening >= 0 AND relationship_deepening <= 1),

    -- Timing
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- One metrics record per session
    UNIQUE(session_id)
);

-- ============================================================================
-- Indexes for Efficient Querying
-- ============================================================================

-- Sessions
CREATE INDEX IF NOT EXISTS idx_collab_sessions_user ON collaboration_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_collab_sessions_type ON collaboration_sessions(collaboration_type);
CREATE INDEX IF NOT EXISTS idx_collab_sessions_active ON collaboration_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_collab_sessions_time ON collaboration_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_collab_sessions_quality ON collaboration_sessions(collaboration_quality);

-- Contributions
CREATE INDEX IF NOT EXISTS idx_collab_contributions_session ON collaboration_contributions(session_id);
CREATE INDEX IF NOT EXISTS idx_collab_contributions_contributor ON collaboration_contributions(contributor);
CREATE INDEX IF NOT EXISTS idx_collab_contributions_time ON collaboration_contributions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collab_contributions_builds ON collaboration_contributions(builds_on);

-- Perspectives
CREATE INDEX IF NOT EXISTS idx_collab_perspectives_session ON collaboration_perspectives(session_id);
CREATE INDEX IF NOT EXISTS idx_collab_perspectives_type ON collaboration_perspectives(perspective_type);
CREATE INDEX IF NOT EXISTS idx_collab_perspectives_contributor ON collaboration_perspectives(contributor);
CREATE INDEX IF NOT EXISTS idx_collab_perspectives_confidence ON collaboration_perspectives(confidence);

-- Syntheses
CREATE INDEX IF NOT EXISTS idx_perspective_syntheses_session ON perspective_syntheses(session_id);
CREATE INDEX IF NOT EXISTS idx_perspective_syntheses_quality ON perspective_syntheses(synthesis_quality);
CREATE INDEX IF NOT EXISTS idx_perspective_syntheses_time ON perspective_syntheses(created_at DESC);

-- Decisions
CREATE INDEX IF NOT EXISTS idx_joint_decisions_session ON joint_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_joint_decisions_framework ON joint_decisions(framework_used);
CREATE INDEX IF NOT EXISTS idx_joint_decisions_consensus ON joint_decisions(consensus_reached);
CREATE INDEX IF NOT EXISTS idx_joint_decisions_time ON joint_decisions(created_at DESC);

-- Learning
CREATE INDEX IF NOT EXISTS idx_mutual_learning_session ON mutual_learning(session_id);
CREATE INDEX IF NOT EXISTS idx_mutual_learning_depth ON mutual_learning(understanding_depth);

-- Metrics
CREATE INDEX IF NOT EXISTS idx_collab_metrics_quality ON collaboration_metrics(decision_quality);
CREATE INDEX IF NOT EXISTS idx_collab_metrics_emergent ON collaboration_metrics(emergent_capability_count);

-- ============================================================================
-- Table Comments
-- ============================================================================

COMMENT ON TABLE collaboration_sessions IS 'Phase 7.1: Active and historical collaboration sessions between human and AI';
COMMENT ON TABLE collaboration_contributions IS 'Phase 7.1: Individual contributions building the collaborative dialogue';
COMMENT ON TABLE collaboration_perspectives IS 'Phase 7.1: Different perspectives added for synthesis';
COMMENT ON TABLE perspective_syntheses IS 'Phase 7.1: Unified views created from multiple perspectives';
COMMENT ON TABLE joint_decisions IS 'Phase 7.1: Decisions made collaboratively with recorded process';
COMMENT ON TABLE mutual_learning IS 'Phase 7.1: What both parties learned from collaboration';
COMMENT ON TABLE collaboration_metrics IS 'Phase 7.1: Computed metrics for collaboration quality';
