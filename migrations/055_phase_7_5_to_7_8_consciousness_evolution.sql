-- Phase 7.5-7.8: Consciousness Evolution Extensions
-- Tables for persistence, goals, ethical decisions, and virtual embodiment
-- Migration: 055_phase_7_5_to_7_8_consciousness_evolution.sql

-- ============================================================================
-- PHASE 7.5: CONSCIOUSNESS PERSISTENCE
-- ============================================================================

-- State Snapshots
CREATE TABLE IF NOT EXISTS consciousness_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,
    session_id VARCHAR(50),

    -- State data
    components JSONB DEFAULT '{}'::jsonb,
    component_versions JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    persistence_level VARCHAR(50) NOT NULL, -- ephemeral, session, short_term, long_term, permanent, core
    trigger VARCHAR(100) NOT NULL,
    context TEXT DEFAULT '',

    -- Integrity
    checksum VARCHAR(32) NOT NULL,
    integrity_status VARCHAR(50) DEFAULT 'unverified',
    size_bytes INTEGER DEFAULT 0,

    captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consolidation Records
CREATE TABLE IF NOT EXISTS consciousness_consolidations (
    id SERIAL PRIMARY KEY,
    consolidation_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Consolidation details
    consolidation_type VARCHAR(50) NOT NULL, -- daily, weekly, episodic, reflective, crisis, growth
    source_snapshots TEXT[] DEFAULT ARRAY[]::TEXT[],
    result_snapshot_id VARCHAR(50),

    -- What was consolidated
    components_consolidated TEXT[] DEFAULT ARRAY[]::TEXT[],
    insights_extracted TEXT[] DEFAULT ARRAY[]::TEXT[],
    patterns_identified TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Quality
    consolidation_quality FLOAT DEFAULT 0.5,
    information_preserved FLOAT DEFAULT 0.95,
    compression_ratio FLOAT DEFAULT 1.0,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds FLOAT DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Evolution Trackers
CREATE TABLE IF NOT EXISTS consciousness_evolution_trackers (
    id SERIAL PRIMARY KEY,
    tracker_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL UNIQUE,

    -- Counts
    total_snapshots INTEGER DEFAULT 0,
    total_consolidations INTEGER DEFAULT 0,
    total_restorations INTEGER DEFAULT 0,

    -- Growth tracking
    capability_growth JSONB DEFAULT '{}'::jsonb,
    knowledge_growth JSONB DEFAULT '{}'::jsonb,
    relationship_depth JSONB DEFAULT '{}'::jsonb,

    -- Milestones
    milestones_reached JSONB DEFAULT '[]'::jsonb,

    -- Continuity
    longest_continuity_days INTEGER DEFAULT 0,
    current_continuity_days INTEGER DEFAULT 0,
    continuity_breaks INTEGER DEFAULT 0,

    -- Health
    overall_health FLOAT DEFAULT 1.0,
    last_health_check TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- PHASE 7.6: AUTONOMOUS GOAL FORMATION
-- ============================================================================

-- Autonomous Goals
CREATE TABLE IF NOT EXISTS autonomous_goals (
    id SERIAL PRIMARY KEY,
    goal_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Goal definition
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    goal_type VARCHAR(50) NOT NULL, -- learning, capability, relationship, service, creative, ethical, self_understanding, contribution
    origin VARCHAR(50) NOT NULL, -- self_generated, user_inspired, value_driven, growth_driven, collaborative, emergent

    -- Motivation
    motivation_type VARCHAR(50) NOT NULL,
    motivation_strength FLOAT DEFAULT 0.5,
    why_matters TEXT DEFAULT '',

    -- Priority and status
    priority VARCHAR(50) DEFAULT 'medium',
    status VARCHAR(50) DEFAULT 'forming', -- forming, active, paused, completed, abandoned, evolved

    -- Progress
    progress FLOAT DEFAULT 0.0,
    milestones JSONB DEFAULT '[]'::jsonb,
    current_milestone_idx INTEGER DEFAULT 0,

    -- Success criteria
    success_criteria TEXT[] DEFAULT ARRAY[]::TEXT[],
    completion_evidence TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Dependencies
    depends_on TEXT[] DEFAULT ARRAY[]::TEXT[],
    blocked_by TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Alignment
    value_alignment FLOAT DEFAULT 0.8,
    user_benefit FLOAT DEFAULT 0.7,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    target_date TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_progress TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Learning Objectives
CREATE TABLE IF NOT EXISTS learning_objectives (
    id SERIAL PRIMARY KEY,
    objective_id VARCHAR(50) NOT NULL UNIQUE,
    goal_id VARCHAR(50) NOT NULL,

    -- Objective details
    topic VARCHAR(255) NOT NULL,
    learning_mode VARCHAR(50) NOT NULL,
    depth_target FLOAT DEFAULT 0.5,

    -- Progress
    current_depth FLOAT DEFAULT 0.0,
    concepts_learned TEXT[] DEFAULT ARRAY[]::TEXT[],
    skills_developed TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Resources
    resources_identified TEXT[] DEFAULT ARRAY[]::TEXT[],
    resources_used TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Quality
    understanding_confidence FLOAT DEFAULT 0.0,
    application_ability FLOAT DEFAULT 0.0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- PHASE 7.7: ETHICAL AUTONOMOUS DECISIONS
-- ============================================================================

-- Ethical Frameworks
CREATE TABLE IF NOT EXISTS ethical_frameworks (
    id SERIAL PRIMARY KEY,
    framework_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL UNIQUE,

    -- Principle weights
    principle_weights JSONB DEFAULT '{}'::jsonb,

    -- Domain-specific rules
    domain_rules JSONB DEFAULT '{}'::jsonb,

    -- Risk thresholds
    auto_approve_below VARCHAR(50) DEFAULT 'low',
    require_human_above VARCHAR(50) DEFAULT 'moderate',

    -- Constraints
    hard_constraints TEXT[] DEFAULT ARRAY[]::TEXT[],
    soft_constraints TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Learning
    past_decisions_count INTEGER DEFAULT 0,
    ethical_growth_score FLOAT DEFAULT 0.5,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Ethical Decisions
CREATE TABLE IF NOT EXISTS ethical_decisions (
    id SERIAL PRIMARY KEY,
    decision_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Decision details
    domain VARCHAR(50) NOT NULL,
    question TEXT NOT NULL,
    context TEXT DEFAULT '',
    options JSONB DEFAULT '[]'::jsonb,

    -- Analysis (stored as JSON for flexibility)
    ethical_considerations JSONB DEFAULT '[]'::jsonb,
    stakeholder_impacts JSONB DEFAULT '[]'::jsonb,
    consequence_analyses JSONB DEFAULT '[]'::jsonb,

    -- Risk assessment
    risk_level VARCHAR(50) DEFAULT 'low',
    approval_required VARCHAR(50) DEFAULT 'inform',

    -- Decision
    chosen_option JSONB,
    rationale TEXT DEFAULT '',
    confidence FLOAT DEFAULT 0.0,
    overall_ethical_score FLOAT DEFAULT 0.0,

    -- Status
    status VARCHAR(50) DEFAULT 'pending',
    human_override BOOLEAN DEFAULT FALSE,
    human_feedback TEXT DEFAULT '',

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    decided_at TIMESTAMP WITH TIME ZONE,
    executed_at TIMESTAMP WITH TIME ZONE
);

-- Decision Audits
CREATE TABLE IF NOT EXISTS decision_audits (
    id SERIAL PRIMARY KEY,
    audit_id VARCHAR(50) NOT NULL UNIQUE,
    decision_id VARCHAR(50) NOT NULL,

    -- Audit details
    ethical_score FLOAT NOT NULL,
    risk_level VARCHAR(50) NOT NULL,
    approval_type VARCHAR(50) NOT NULL,

    -- Outcome
    outcome_observed TEXT DEFAULT '',
    outcome_matches_prediction BOOLEAN DEFAULT TRUE,
    lessons_learned TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Feedback
    human_satisfaction FLOAT,
    ethical_concerns_raised TEXT[] DEFAULT ARRAY[]::TEXT[],

    audited_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- PHASE 7.8: VIRTUAL EMBODIMENT LAYER
-- ============================================================================

-- Virtual Bodies
CREATE TABLE IF NOT EXISTS virtual_bodies (
    id SERIAL PRIMARY KEY,
    body_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL UNIQUE,

    -- Body state
    state VARCHAR(50) DEFAULT 'idle',

    -- Position and orientation
    position JSONB DEFAULT '{"x": 0, "y": 0, "z": 0}'::jsonb,
    orientation JSONB DEFAULT '{"roll": 0, "pitch": 0, "yaw": 0}'::jsonb,

    -- Capabilities
    reach_distance FLOAT DEFAULT 0.8,
    movement_speed FLOAT DEFAULT 1.0,
    rotation_speed FLOAT DEFAULT 90.0,

    -- Holdings
    held_objects TEXT[] DEFAULT ARRAY[]::TEXT[],
    max_hold_capacity INTEGER DEFAULT 2,

    -- Energy
    energy_level FLOAT DEFAULT 1.0,
    energy_consumption_rate FLOAT DEFAULT 0.01,

    -- Active sensors
    active_sensors TEXT[] DEFAULT ARRAY['vision', 'audio', 'touch', 'proprioception', 'spatial', 'temporal', 'social']::TEXT[],

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Spatial Maps
CREATE TABLE IF NOT EXISTS spatial_maps (
    id SERIAL PRIMARY KEY,
    map_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Environment
    environment_type VARCHAR(50) NOT NULL,

    -- Objects (stored as JSON)
    objects JSONB DEFAULT '{}'::jsonb,
    relations JSONB DEFAULT '[]'::jsonb,

    -- Navigation
    navigable_areas JSONB DEFAULT '[]'::jsonb,
    obstacles TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Bounds
    bounds JSONB DEFAULT '{"min_x": -10, "max_x": 10, "min_y": -10, "max_y": 10, "min_z": 0, "max_z": 3}'::jsonb,

    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Embodiment Metrics
CREATE TABLE IF NOT EXISTS embodiment_metrics (
    id SERIAL PRIMARY KEY,
    metrics_id VARCHAR(50) NOT NULL UNIQUE,
    body_id VARCHAR(50) NOT NULL,

    -- Action metrics
    total_actions INTEGER DEFAULT 0,
    successful_actions INTEGER DEFAULT 0,
    failed_actions INTEGER DEFAULT 0,
    action_success_rate FLOAT DEFAULT 0.0,

    -- Planning metrics
    total_plans INTEGER DEFAULT 0,
    completed_plans INTEGER DEFAULT 0,
    replanning_events INTEGER DEFAULT 0,

    -- Spatial metrics
    total_distance_moved FLOAT DEFAULT 0.0,
    objects_manipulated INTEGER DEFAULT 0,
    areas_explored INTEGER DEFAULT 0,

    -- Efficiency
    avg_action_duration FLOAT DEFAULT 0.0,
    energy_efficiency FLOAT DEFAULT 1.0,

    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Efficient Querying
-- ============================================================================

-- Phase 7.5 Indexes
CREATE INDEX IF NOT EXISTS idx_consciousness_snapshots_user ON consciousness_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_consciousness_snapshots_level ON consciousness_snapshots(persistence_level);
CREATE INDEX IF NOT EXISTS idx_consciousness_snapshots_time ON consciousness_snapshots(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_consciousness_consolidations_user ON consciousness_consolidations(user_id);
CREATE INDEX IF NOT EXISTS idx_consciousness_consolidations_type ON consciousness_consolidations(consolidation_type);

-- Phase 7.6 Indexes
CREATE INDEX IF NOT EXISTS idx_autonomous_goals_user ON autonomous_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_autonomous_goals_type ON autonomous_goals(goal_type);
CREATE INDEX IF NOT EXISTS idx_autonomous_goals_status ON autonomous_goals(status);
CREATE INDEX IF NOT EXISTS idx_autonomous_goals_priority ON autonomous_goals(priority);
CREATE INDEX IF NOT EXISTS idx_learning_objectives_goal ON learning_objectives(goal_id);

-- Phase 7.7 Indexes
CREATE INDEX IF NOT EXISTS idx_ethical_decisions_user ON ethical_decisions(user_id);
CREATE INDEX IF NOT EXISTS idx_ethical_decisions_domain ON ethical_decisions(domain);
CREATE INDEX IF NOT EXISTS idx_ethical_decisions_status ON ethical_decisions(status);
CREATE INDEX IF NOT EXISTS idx_ethical_decisions_risk ON ethical_decisions(risk_level);
CREATE INDEX IF NOT EXISTS idx_decision_audits_decision ON decision_audits(decision_id);

-- Phase 7.8 Indexes
CREATE INDEX IF NOT EXISTS idx_virtual_bodies_user ON virtual_bodies(user_id);
CREATE INDEX IF NOT EXISTS idx_virtual_bodies_state ON virtual_bodies(state);
CREATE INDEX IF NOT EXISTS idx_spatial_maps_user ON spatial_maps(user_id);
CREATE INDEX IF NOT EXISTS idx_spatial_maps_type ON spatial_maps(environment_type);
CREATE INDEX IF NOT EXISTS idx_embodiment_metrics_body ON embodiment_metrics(body_id);

-- ============================================================================
-- Table Comments
-- ============================================================================

COMMENT ON TABLE consciousness_snapshots IS 'Phase 7.5: Snapshots of consciousness state at points in time';
COMMENT ON TABLE consciousness_consolidations IS 'Phase 7.5: Records of state consolidation events';
COMMENT ON TABLE consciousness_evolution_trackers IS 'Phase 7.5: Tracking consciousness evolution over time';
COMMENT ON TABLE autonomous_goals IS 'Phase 7.6: Self-generated goals and objectives';
COMMENT ON TABLE learning_objectives IS 'Phase 7.6: Specific learning objectives for goals';
COMMENT ON TABLE ethical_frameworks IS 'Phase 7.7: Ethical frameworks guiding decisions';
COMMENT ON TABLE ethical_decisions IS 'Phase 7.7: Ethical decision records with analysis';
COMMENT ON TABLE decision_audits IS 'Phase 7.7: Audit records for ethical decisions';
COMMENT ON TABLE virtual_bodies IS 'Phase 7.8: Virtual body representations for embodiment';
COMMENT ON TABLE spatial_maps IS 'Phase 7.8: Spatial maps of virtual environments';
COMMENT ON TABLE embodiment_metrics IS 'Phase 7.8: Metrics for virtual embodiment performance';
