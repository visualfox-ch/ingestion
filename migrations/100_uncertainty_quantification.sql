-- Phase A2: Uncertainty Quantification
-- Based on Bayesian approaches and metacognition research
-- Enables Jarvis to know what he doesn't know
-- Date: 2026-03-15

-- Uncertainty assessments: tracks confidence for each response
CREATE TABLE IF NOT EXISTS uncertainty_assessments (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    query_hash VARCHAR(64),
    query_text TEXT,

    -- Overall confidence
    overall_confidence FLOAT NOT NULL,  -- 0-1 scale
    confidence_category VARCHAR(20),     -- very_low, low, medium, high, very_high

    -- Component confidences
    knowledge_confidence FLOAT,          -- Do I have relevant knowledge?
    reasoning_confidence FLOAT,          -- Is my reasoning sound?
    factual_confidence FLOAT,            -- Are my facts correct?
    completeness_confidence FLOAT,       -- Did I cover everything?

    -- Uncertainty signals detected
    uncertainty_signals JSONB DEFAULT '[]',  -- [{type, description, impact}]
    knowledge_gaps JSONB DEFAULT '[]',       -- [{topic, severity}]

    -- Calibration tracking
    was_correct BOOLEAN,                 -- For calibration (filled later)
    calibration_score FLOAT,             -- How well-calibrated was the confidence?

    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Knowledge gaps: systematic tracking of what Jarvis doesn't know
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    domain VARCHAR(100),
    severity VARCHAR(20) DEFAULT 'medium',  -- low, medium, high, critical

    -- Gap details
    description TEXT,
    example_queries JSONB DEFAULT '[]',
    occurrence_count INTEGER DEFAULT 1,
    last_encountered TIMESTAMPTZ DEFAULT NOW(),

    -- Resolution
    is_resolved BOOLEAN DEFAULT FALSE,
    resolution_method TEXT,  -- learned, external_source, acknowledged_limitation
    resolved_at TIMESTAMPTZ,

    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(topic, domain)
);

-- Confidence calibration: tracks how accurate confidence predictions are
CREATE TABLE IF NOT EXISTS confidence_calibration (
    id SERIAL PRIMARY KEY,
    calibration_date DATE NOT NULL,
    confidence_bucket VARCHAR(20) NOT NULL,  -- 0-20, 20-40, 40-60, 60-80, 80-100

    -- Calibration metrics
    predictions_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    accuracy_rate FLOAT,  -- correct_count / predictions_count

    -- Expected vs actual
    expected_accuracy FLOAT,  -- midpoint of bucket
    calibration_error FLOAT,  -- |expected - actual|

    -- By category
    category_breakdown JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(calibration_date, confidence_bucket)
);

-- Uncertainty signals: patterns that indicate low confidence
CREATE TABLE IF NOT EXISTS uncertainty_signals (
    id SERIAL PRIMARY KEY,
    signal_name VARCHAR(100) NOT NULL UNIQUE,
    signal_type VARCHAR(50) NOT NULL,  -- linguistic, knowledge, reasoning, temporal

    -- Detection
    detection_pattern TEXT,  -- regex or keyword pattern
    detection_method VARCHAR(50),  -- pattern, semantic, heuristic

    -- Impact
    confidence_impact FLOAT DEFAULT -0.1,  -- How much to reduce confidence
    severity VARCHAR(20) DEFAULT 'medium',

    -- Examples
    examples JSONB DEFAULT '[]',

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_uncertainty_session ON uncertainty_assessments(session_id);
CREATE INDEX IF NOT EXISTS idx_uncertainty_confidence ON uncertainty_assessments(overall_confidence);
CREATE INDEX IF NOT EXISTS idx_uncertainty_created ON uncertainty_assessments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_topic ON knowledge_gaps(topic);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_domain ON knowledge_gaps(domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_severity ON knowledge_gaps(severity);
CREATE INDEX IF NOT EXISTS idx_calibration_date ON confidence_calibration(calibration_date DESC);

-- Default uncertainty signals
INSERT INTO uncertainty_signals (signal_name, signal_type, detection_pattern, confidence_impact, severity) VALUES
-- Linguistic signals
('hedging_language', 'linguistic', 'vielleicht|möglicherweise|eventuell|könnte sein|wahrscheinlich|vermutlich|maybe|perhaps|possibly|might|could be', -0.15, 'medium'),
('uncertainty_phrases', 'linguistic', 'ich bin nicht sicher|I am not sure|ich weiss nicht genau|not entirely certain|hard to say', -0.25, 'high'),
('speculation_markers', 'linguistic', 'ich vermute|I guess|I suppose|ich nehme an|I would assume|my best guess', -0.20, 'medium'),
('approximation_language', 'linguistic', 'ungefähr|etwa|circa|approximately|around|roughly|more or less', -0.10, 'low'),

-- Knowledge signals
('knowledge_gap_explicit', 'knowledge', 'ich habe keine Informationen|I don''t have information|ausserhalb meines Wissens|beyond my knowledge', -0.35, 'critical'),
('outdated_knowledge', 'knowledge', 'mein Wissen reicht bis|my knowledge cutoff|may have changed since|könnte sich geändert haben', -0.20, 'medium'),
('domain_unfamiliarity', 'knowledge', 'nicht mein Fachgebiet|not my area of expertise|I''m not specialized in', -0.25, 'high'),

-- Reasoning signals
('conditional_reasoning', 'reasoning', 'falls|wenn|sofern|vorausgesetzt|if|assuming|provided that|given that', -0.05, 'low'),
('multiple_interpretations', 'reasoning', 'es kommt darauf an|it depends|there are multiple ways|mehrere Möglichkeiten', -0.10, 'low'),
('complex_tradeoffs', 'reasoning', 'einerseits.*andererseits|on one hand.*on the other|pros and cons|Vor- und Nachteile', -0.05, 'low'),

-- Temporal signals
('temporal_uncertainty', 'temporal', 'momentan|currently|at the moment|zur Zeit|as of now|stand heute', -0.10, 'low'),
('future_prediction', 'temporal', 'in Zukunft|in the future|wird wahrscheinlich|will likely|expected to', -0.15, 'medium')
ON CONFLICT (signal_name) DO NOTHING;

-- Comments
COMMENT ON TABLE uncertainty_assessments IS 'Phase A2: Tracks confidence levels for responses';
COMMENT ON TABLE knowledge_gaps IS 'Phase A2: Systematic tracking of knowledge limitations';
COMMENT ON TABLE confidence_calibration IS 'Phase A2: Measures how well-calibrated confidence predictions are';
COMMENT ON TABLE uncertainty_signals IS 'Phase A2: Patterns that indicate uncertainty in responses';
