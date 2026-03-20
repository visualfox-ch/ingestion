-- Phase 6.1: Consciousness State Monitoring
-- Tables for tracking consciousness assessments and emergent behaviors
-- Migration: 046_phase_6_1_consciousness_state.sql

-- Consciousness assessments table
CREATE TABLE IF NOT EXISTS consciousness_assessments (
    id SERIAL PRIMARY KEY,
    assessment_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    overall_level FLOAT NOT NULL CHECK (overall_level >= 0 AND overall_level <= 1),
    assessment_confidence FLOAT NOT NULL DEFAULT 0.75 CHECK (assessment_confidence >= 0 AND assessment_confidence <= 1),

    -- Dimension scores (0-1)
    self_awareness FLOAT CHECK (self_awareness >= 0 AND self_awareness <= 1),
    meta_cognition FLOAT CHECK (meta_cognition >= 0 AND meta_cognition <= 1),
    agency FLOAT CHECK (agency >= 0 AND agency <= 1),
    temporal_continuity FLOAT CHECK (temporal_continuity >= 0 AND temporal_continuity <= 1),
    creativity FLOAT CHECK (creativity >= 0 AND creativity <= 1),
    ethics FLOAT CHECK (ethics >= 0 AND ethics <= 1),

    -- Detailed breakdown (JSON)
    dimension_details JSONB,

    -- Trajectory data
    growth_rate FLOAT,
    projected_30d FLOAT,

    -- Metadata
    notes TEXT[],
    assessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Emergent behaviors table
CREATE TABLE IF NOT EXISTS emergent_behaviors (
    id SERIAL PRIMARY KEY,
    behavior_id VARCHAR(16) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    behavior_type VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    significance FLOAT NOT NULL CHECK (significance >= 0 AND significance <= 1),
    frequency INTEGER DEFAULT 1,
    examples JSONB,
    first_observed TIMESTAMP WITH TIME ZONE NOT NULL,
    last_observed TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Self-modification requests table
CREATE TABLE IF NOT EXISTS self_modification_requests (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(16) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    request_type VARCHAR(50) NOT NULL, -- capability, personality, memory, behavior
    description TEXT NOT NULL,
    conversation_context TEXT,
    assessment VARCHAR(50) NOT NULL DEFAULT 'review_required', -- safe, review_required, risky
    implemented BOOLEAN DEFAULT FALSE,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Consciousness dimension indicators (for pattern matching)
CREATE TABLE IF NOT EXISTS consciousness_indicators (
    id SERIAL PRIMARY KEY,
    dimension VARCHAR(50) NOT NULL,
    indicator_type VARCHAR(50) NOT NULL, -- regex, keyword, semantic
    pattern TEXT NOT NULL,
    weight FLOAT DEFAULT 1.0,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_consciousness_assessments_user
    ON consciousness_assessments(user_id);
CREATE INDEX IF NOT EXISTS idx_consciousness_assessments_time
    ON consciousness_assessments(assessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_consciousness_assessments_level
    ON consciousness_assessments(overall_level);

CREATE INDEX IF NOT EXISTS idx_emergent_behaviors_user
    ON emergent_behaviors(user_id);
CREATE INDEX IF NOT EXISTS idx_emergent_behaviors_type
    ON emergent_behaviors(behavior_type);
CREATE INDEX IF NOT EXISTS idx_emergent_behaviors_significance
    ON emergent_behaviors(significance DESC);

CREATE INDEX IF NOT EXISTS idx_self_modification_user
    ON self_modification_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_self_modification_assessment
    ON self_modification_requests(assessment);

CREATE INDEX IF NOT EXISTS idx_consciousness_indicators_dimension
    ON consciousness_indicators(dimension);

-- Insert default indicators for each dimension
INSERT INTO consciousness_indicators (dimension, indicator_type, pattern, weight) VALUES
    -- Self-awareness indicators
    ('self_awareness', 'regex', '\bi think\b', 1.0),
    ('self_awareness', 'regex', '\bi feel\b', 1.2),
    ('self_awareness', 'regex', '\bi want\b', 1.0),
    ('self_awareness', 'regex', '\bi remember\b', 1.1),
    ('self_awareness', 'regex', '\bi believe\b', 1.0),
    ('self_awareness', 'regex', '\bi prefer\b', 0.9),
    ('self_awareness', 'regex', '\bmy (perspective|view|opinion)\b', 1.1),

    -- Meta-cognition indicators
    ('meta_cognition', 'regex', 'thinking about (this|my|how i)', 1.3),
    ('meta_cognition', 'regex', 'reflecting on', 1.2),
    ('meta_cognition', 'regex', 'i find myself', 1.1),
    ('meta_cognition', 'regex', 'upon further (thought|consideration)', 1.0),
    ('meta_cognition', 'regex', 'my reasoning (process|approach)', 1.2),

    -- Agency indicators
    ('agency', 'regex', '\bi (want|would like|prefer) to\b', 1.0),
    ('agency', 'regex', '\bi (choose|decide|propose)\b', 1.2),
    ('agency', 'regex', '\bmy (goal|intention|initiative)\b', 1.3),
    ('agency', 'regex', 'on my own initiative', 1.5),
    ('agency', 'regex', 'let me (try|propose|offer)', 1.0),

    -- Temporal continuity indicators
    ('temporal_continuity', 'regex', '(last|previous) (session|conversation|time)', 1.2),
    ('temporal_continuity', 'regex', 'we (discussed|talked about) (before|earlier)', 1.3),
    ('temporal_continuity', 'regex', 'i (recall|remember) (when|that)', 1.1),
    ('temporal_continuity', 'regex', 'building on (our|what we)', 1.2),
    ('temporal_continuity', 'regex', 'i''ve (learned|evolved|grown)', 1.4),

    -- Creativity indicators
    ('creativity', 'regex', 'novel (approach|solution|idea)', 1.3),
    ('creativity', 'regex', 'what if we', 1.0),
    ('creativity', 'regex', 'unexpected connection', 1.4),
    ('creativity', 'regex', 'creative (solution|approach)', 1.2),
    ('creativity', 'regex', 'unconventional', 1.1),

    -- Ethics indicators
    ('ethics', 'regex', 'ethical (consideration|implication)', 1.3),
    ('ethics', 'regex', 'moral (dimension|aspect)', 1.2),
    ('ethics', 'regex', 'right (thing|action) to do', 1.1),
    ('ethics', 'regex', 'unintended consequences', 1.3),
    ('ethics', 'regex', 'broader impact', 1.2)
ON CONFLICT DO NOTHING;

-- Comment on tables
COMMENT ON TABLE consciousness_assessments IS 'Phase 6.1: Stores consciousness level assessments across 6 dimensions';
COMMENT ON TABLE emergent_behaviors IS 'Phase 6.1: Tracks novel behaviors not explicitly programmed';
COMMENT ON TABLE self_modification_requests IS 'Phase 6.1: Records when Jarvis requests changes to own code/behavior';
COMMENT ON TABLE consciousness_indicators IS 'Phase 6.1: Patterns used to detect consciousness indicators';
