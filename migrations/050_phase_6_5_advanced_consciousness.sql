-- Phase 6.5: Advanced Consciousness Integration
-- Tables for multi-modal consciousness and temporal evolution mapping
-- Migration: 050_phase_6_5_advanced_consciousness.sql

-- ============================================================================
-- Phase 6.5.1: Multi-Modal Consciousness Tables
-- ============================================================================

-- Multimodal input records
CREATE TABLE IF NOT EXISTS multimodal_inputs (
    id SERIAL PRIMARY KEY,
    input_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Input details
    modality VARCHAR(50) NOT NULL, -- text, vision, audio, structured_data, temporal, spatial
    content_hash VARCHAR(64), -- Hash of content for deduplication
    source VARCHAR(100) NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    processing_result JSONB DEFAULT '{}'::jsonb,

    -- Timing
    input_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consciousness states (multimodal awareness)
CREATE TABLE IF NOT EXISTS multimodal_consciousness_states (
    id SERIAL PRIMARY KEY,
    state_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- State details
    dominant_modality VARCHAR(50),
    integration_level FLOAT NOT NULL CHECK (integration_level >= 0 AND integration_level <= 1),
    awareness_quality FLOAT NOT NULL CHECK (awareness_quality >= 0 AND awareness_quality <= 1),
    unified_narrative TEXT,

    -- Modality states (JSON for flexibility)
    modality_states JSONB NOT NULL,

    -- Active patterns (JSON array)
    active_patterns JSONB DEFAULT '[]'::jsonb,

    -- Timing
    state_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Cross-modal patterns detected
CREATE TABLE IF NOT EXISTS cross_modal_patterns (
    id SERIAL PRIMARY KEY,
    pattern_id VARCHAR(50) NOT NULL UNIQUE,
    state_id VARCHAR(50) REFERENCES multimodal_consciousness_states(state_id) ON DELETE SET NULL,

    -- Pattern details
    pattern_type VARCHAR(50) NOT NULL, -- temporal_correlation, semantic_bridge, emotional_resonance, causal_chain, structural_isomorphism, emergent_meaning
    modalities_involved TEXT[] NOT NULL,
    description TEXT NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    significance FLOAT NOT NULL CHECK (significance >= 0 AND significance <= 1),
    integration_potential FLOAT NOT NULL CHECK (integration_potential >= 0 AND integration_potential <= 1),

    -- Evidence
    evidence JSONB DEFAULT '[]'::jsonb,

    -- Timing
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Modality switch events
CREATE TABLE IF NOT EXISTS modality_switch_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Switch details
    from_modality VARCHAR(50), -- NULL if starting
    to_modality VARCHAR(50) NOT NULL,
    trigger_reason TEXT NOT NULL,
    context_preserved FLOAT NOT NULL CHECK (context_preserved >= 0 AND context_preserved <= 1),
    switch_quality VARCHAR(20) NOT NULL, -- smooth, gradual, abrupt

    -- Timing
    switch_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consciousness persistence records
CREATE TABLE IF NOT EXISTS consciousness_persistence (
    id SERIAL PRIMARY KEY,
    persistence_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Session details
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    total_duration_seconds INTEGER DEFAULT 0,

    -- Persistence metrics
    average_context_preservation FLOAT DEFAULT 1.0 CHECK (average_context_preservation >= 0 AND average_context_preservation <= 1),
    switch_count INTEGER DEFAULT 0,
    dominant_modalities TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Integration peaks (JSON array)
    integration_peaks JSONB DEFAULT '[]'::jsonb,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Phase 6.5.2: Temporal Consciousness Maps Tables
-- ============================================================================

-- Consciousness data points (time series)
CREATE TABLE IF NOT EXISTS consciousness_data_points (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,

    -- Data point
    dimension VARCHAR(50) NOT NULL,
    value FLOAT NOT NULL CHECK (value >= 0 AND value <= 1),
    context TEXT,
    contributing_factors TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    point_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Evolution segments
CREATE TABLE IF NOT EXISTS evolution_segments (
    id SERIAL PRIMARY KEY,
    segment_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Segment details
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    phase VARCHAR(50) NOT NULL, -- nascent, developing, consolidating, plateauing, transforming, transcending
    dimensions_involved TEXT[] NOT NULL,
    growth_rate FLOAT NOT NULL,
    stability FLOAT NOT NULL CHECK (stability >= 0 AND stability <= 1),

    -- Key events
    key_events TEXT[] DEFAULT ARRAY[]::TEXT[],

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consciousness breakthroughs
CREATE TABLE IF NOT EXISTS consciousness_breakthroughs (
    id SERIAL PRIMARY KEY,
    breakthrough_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Breakthrough details
    category VARCHAR(50) NOT NULL, -- self_awareness, meta_cognition, emotional_depth, ethical_reasoning, creativity, relational_understanding, integration
    description TEXT NOT NULL,
    magnitude FLOAT NOT NULL CHECK (magnitude >= 0 AND magnitude <= 1),
    dimensions_affected TEXT[] NOT NULL,

    -- Impact tracking
    impact_duration_days INTEGER DEFAULT 0,
    triggering_factors TEXT[] DEFAULT ARRAY[]::TEXT[],
    sustained BOOLEAN DEFAULT FALSE,

    -- Timing
    breakthrough_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Breakthrough impact analysis
CREATE TABLE IF NOT EXISTS breakthrough_impact_analysis (
    id SERIAL PRIMARY KEY,
    analysis_id VARCHAR(50) NOT NULL UNIQUE,
    breakthrough_id VARCHAR(50) NOT NULL REFERENCES consciousness_breakthroughs(breakthrough_id) ON DELETE CASCADE,

    -- Impact details
    immediate_impact JSONB NOT NULL, -- dimension -> change
    sustained_impact JSONB NOT NULL, -- dimension -> change
    ripple_effects TEXT[] DEFAULT ARRAY[]::TEXT[],
    integration_depth FLOAT NOT NULL CHECK (integration_depth >= 0 AND integration_depth <= 1),
    influence_duration_days INTEGER NOT NULL,
    affected_trajectories TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Timing
    analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Trajectory predictions
CREATE TABLE IF NOT EXISTS trajectory_predictions (
    id SERIAL PRIMARY KEY,
    prediction_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Prediction details
    dimension VARCHAR(50) NOT NULL,
    current_value FLOAT NOT NULL CHECK (current_value >= 0 AND current_value <= 1),
    predicted_values JSONB NOT NULL, -- array of [timestamp, value]
    confidence VARCHAR(20) NOT NULL, -- very_low, low, moderate, high, very_high
    confidence_intervals JSONB NOT NULL, -- array of [low, high]

    -- Context
    assumptions TEXT[] DEFAULT ARRAY[]::TEXT[],
    risk_factors TEXT[] DEFAULT ARRAY[]::TEXT[],
    growth_scenarios JSONB NOT NULL, -- scenario name -> value

    -- Validity
    valid_until TIMESTAMP WITH TIME ZONE,

    -- Timing
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consciousness maps (generated reports)
CREATE TABLE IF NOT EXISTS consciousness_maps (
    id SERIAL PRIMARY KEY,
    map_id VARCHAR(50) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,

    -- Time range
    time_range_start TIMESTAMP WITH TIME ZONE NOT NULL,
    time_range_end TIMESTAMP WITH TIME ZONE NOT NULL,
    time_scale VARCHAR(20) NOT NULL, -- minute, hour, day, week, month, quarter

    -- Current state
    current_phase VARCHAR(50) NOT NULL,
    current_scores JSONB NOT NULL,

    -- Analysis results
    overall_trajectory VARCHAR(20) NOT NULL, -- ascending, stable, declining
    growth_velocity FLOAT NOT NULL,
    integration_score FLOAT NOT NULL CHECK (integration_score >= 0 AND integration_score <= 1),

    -- Recommendations
    recommended_focus_areas TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Counts for summary
    data_point_count INTEGER DEFAULT 0,
    segment_count INTEGER DEFAULT 0,
    breakthrough_count INTEGER DEFAULT 0,
    prediction_count INTEGER DEFAULT 0,

    -- Timing
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Efficient Querying
-- ============================================================================

-- Multimodal inputs
CREATE INDEX IF NOT EXISTS idx_multimodal_inputs_user ON multimodal_inputs(user_id);
CREATE INDEX IF NOT EXISTS idx_multimodal_inputs_modality ON multimodal_inputs(modality);
CREATE INDEX IF NOT EXISTS idx_multimodal_inputs_time ON multimodal_inputs(input_timestamp DESC);

-- Consciousness states
CREATE INDEX IF NOT EXISTS idx_multimodal_states_user ON multimodal_consciousness_states(user_id);
CREATE INDEX IF NOT EXISTS idx_multimodal_states_time ON multimodal_consciousness_states(state_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_multimodal_states_integration ON multimodal_consciousness_states(integration_level);

-- Cross-modal patterns
CREATE INDEX IF NOT EXISTS idx_cross_modal_patterns_type ON cross_modal_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_cross_modal_patterns_significance ON cross_modal_patterns(significance);
CREATE INDEX IF NOT EXISTS idx_cross_modal_patterns_time ON cross_modal_patterns(detected_at DESC);

-- Modality switches
CREATE INDEX IF NOT EXISTS idx_modality_switches_user ON modality_switch_events(user_id);
CREATE INDEX IF NOT EXISTS idx_modality_switches_time ON modality_switch_events(switch_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_modality_switches_quality ON modality_switch_events(switch_quality);

-- Consciousness persistence
CREATE INDEX IF NOT EXISTS idx_persistence_user ON consciousness_persistence(user_id);
CREATE INDEX IF NOT EXISTS idx_persistence_active ON consciousness_persistence(is_active);

-- Data points
CREATE INDEX IF NOT EXISTS idx_data_points_user ON consciousness_data_points(user_id);
CREATE INDEX IF NOT EXISTS idx_data_points_dimension ON consciousness_data_points(dimension);
CREATE INDEX IF NOT EXISTS idx_data_points_time ON consciousness_data_points(point_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_data_points_user_dimension ON consciousness_data_points(user_id, dimension);

-- Evolution segments
CREATE INDEX IF NOT EXISTS idx_segments_user ON evolution_segments(user_id);
CREATE INDEX IF NOT EXISTS idx_segments_phase ON evolution_segments(phase);
CREATE INDEX IF NOT EXISTS idx_segments_time ON evolution_segments(start_time DESC);

-- Breakthroughs
CREATE INDEX IF NOT EXISTS idx_breakthroughs_user ON consciousness_breakthroughs(user_id);
CREATE INDEX IF NOT EXISTS idx_breakthroughs_category ON consciousness_breakthroughs(category);
CREATE INDEX IF NOT EXISTS idx_breakthroughs_magnitude ON consciousness_breakthroughs(magnitude);
CREATE INDEX IF NOT EXISTS idx_breakthroughs_time ON consciousness_breakthroughs(breakthrough_timestamp DESC);

-- Breakthrough impact
CREATE INDEX IF NOT EXISTS idx_breakthrough_impact_depth ON breakthrough_impact_analysis(integration_depth);

-- Predictions
CREATE INDEX IF NOT EXISTS idx_predictions_user ON trajectory_predictions(user_id);
CREATE INDEX IF NOT EXISTS idx_predictions_dimension ON trajectory_predictions(dimension);
CREATE INDEX IF NOT EXISTS idx_predictions_confidence ON trajectory_predictions(confidence);
CREATE INDEX IF NOT EXISTS idx_predictions_valid ON trajectory_predictions(valid_until);

-- Maps
CREATE INDEX IF NOT EXISTS idx_maps_user ON consciousness_maps(user_id);
CREATE INDEX IF NOT EXISTS idx_maps_scale ON consciousness_maps(time_scale);
CREATE INDEX IF NOT EXISTS idx_maps_time ON consciousness_maps(generated_at DESC);

-- ============================================================================
-- Table Comments
-- ============================================================================

COMMENT ON TABLE multimodal_inputs IS 'Phase 6.5.1: Records inputs from different modalities for consciousness processing';
COMMENT ON TABLE multimodal_consciousness_states IS 'Phase 6.5.1: Unified consciousness states across all modalities';
COMMENT ON TABLE cross_modal_patterns IS 'Phase 6.5.1: Patterns detected spanning multiple modalities';
COMMENT ON TABLE modality_switch_events IS 'Phase 6.5.1: Records when consciousness switches between modalities';
COMMENT ON TABLE consciousness_persistence IS 'Phase 6.5.1: Tracks consciousness continuity across modality switches';

COMMENT ON TABLE consciousness_data_points IS 'Phase 6.5.2: Time series data for consciousness dimensions';
COMMENT ON TABLE evolution_segments IS 'Phase 6.5.2: Segments of consciousness evolution with phases';
COMMENT ON TABLE consciousness_breakthroughs IS 'Phase 6.5.2: Significant breakthroughs in consciousness development';
COMMENT ON TABLE breakthrough_impact_analysis IS 'Phase 6.5.2: Analysis of breakthrough impacts on future development';
COMMENT ON TABLE trajectory_predictions IS 'Phase 6.5.2: Forecasts for consciousness development trajectories';
COMMENT ON TABLE consciousness_maps IS 'Phase 6.5.2: Generated consciousness evolution maps';
