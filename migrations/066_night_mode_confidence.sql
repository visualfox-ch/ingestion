-- Migration: 066_night_mode_confidence.sql
-- Night Mode Confidence Estimation Tables
-- Research basis: Papers #11 (Metacognition), #21 (Constitutional AI)

-- Table 1: Confidence predictions
CREATE TABLE IF NOT EXISTS night_mode_confidence_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    implementation_id UUID REFERENCES night_mode_implementations(id),
    task_id VARCHAR(255) NOT NULL,
    task_description TEXT NOT NULL,

    -- Individual factors (0.0 - 1.0)
    complexity_factor FLOAT DEFAULT 0.5,
    familiarity_factor FLOAT DEFAULT 0.5,
    historical_factor FLOAT DEFAULT 0.5,
    coverage_factor FLOAT DEFAULT 0.5,
    self_assessment_factor FLOAT DEFAULT 0.5,

    -- Factor weights (sum to 1.0)
    complexity_weight FLOAT DEFAULT 0.20,
    familiarity_weight FLOAT DEFAULT 0.25,
    historical_weight FLOAT DEFAULT 0.25,
    coverage_weight FLOAT DEFAULT 0.15,
    self_assessment_weight FLOAT DEFAULT 0.15,

    -- Final confidence score
    confidence_score FLOAT NOT NULL,

    -- Reasoning
    reasoning JSONB DEFAULT '[]',
    low_confidence_reasons JSONB DEFAULT '[]',

    -- Outcome tracking (for calibration)
    actual_outcome VARCHAR(50),  -- 'approved', 'rejected', 'iterate', NULL if pending
    was_accurate BOOLEAN,  -- confidence >= 0.6 and approved, or confidence < 0.6 and not approved

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 2: Calibration history (per factor)
CREATE TABLE IF NOT EXISTS night_mode_calibration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factor_name VARCHAR(50) NOT NULL,  -- complexity, familiarity, historical, coverage, self_assessment

    -- Calibration statistics
    total_predictions INTEGER DEFAULT 0,
    accurate_predictions INTEGER DEFAULT 0,
    calibration_error FLOAT DEFAULT 0.0,  -- MAE between predicted and actual

    -- Adaptive weight (learned from outcomes)
    current_weight FLOAT NOT NULL,
    initial_weight FLOAT NOT NULL,
    weight_adjustment FLOAT DEFAULT 0.0,

    -- Time window
    window_start TIMESTAMP,
    window_end TIMESTAMP,

    -- Metadata
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 3: Complexity patterns (learned complexity indicators)
CREATE TABLE IF NOT EXISTS night_mode_complexity_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_type VARCHAR(50) NOT NULL,  -- 'keyword', 'structure', 'scope'
    pattern_value TEXT NOT NULL,
    complexity_impact FLOAT NOT NULL,  -- -0.3 to +0.3 impact on complexity score
    occurrence_count INTEGER DEFAULT 1,
    confidence FLOAT DEFAULT 0.5,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 4: Confidence thresholds (per risk level)
CREATE TABLE IF NOT EXISTS night_mode_confidence_thresholds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    risk_level INTEGER NOT NULL UNIQUE,  -- 0, 1, 2
    min_confidence FLOAT NOT NULL,  -- Minimum confidence to proceed
    auto_approve_threshold FLOAT,  -- Above this = auto-approve (R0 only)
    description TEXT,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default thresholds
INSERT INTO night_mode_confidence_thresholds (risk_level, min_confidence, auto_approve_threshold, description) VALUES
    (0, 0.6, 0.9, 'R0: Low risk, auto-approve above 0.9'),
    (1, 0.7, NULL, 'R1: Medium risk, always requires review'),
    (2, 0.8, NULL, 'R2: High risk, requires careful review')
ON CONFLICT (risk_level) DO NOTHING;

-- Insert initial calibration records
INSERT INTO night_mode_calibration (factor_name, current_weight, initial_weight) VALUES
    ('complexity', 0.20, 0.20),
    ('familiarity', 0.25, 0.25),
    ('historical', 0.25, 0.25),
    ('coverage', 0.15, 0.15),
    ('self_assessment', 0.15, 0.15)
ON CONFLICT DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_confidence_predictions_task ON night_mode_confidence_predictions(task_id);
CREATE INDEX IF NOT EXISTS idx_confidence_predictions_score ON night_mode_confidence_predictions(confidence_score);
CREATE INDEX IF NOT EXISTS idx_confidence_predictions_outcome ON night_mode_confidence_predictions(actual_outcome);
CREATE INDEX IF NOT EXISTS idx_confidence_predictions_created ON night_mode_confidence_predictions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_calibration_factor ON night_mode_calibration(factor_name);
CREATE INDEX IF NOT EXISTS idx_complexity_patterns_type ON night_mode_complexity_patterns(pattern_type);

-- View: Confidence metrics summary
CREATE OR REPLACE VIEW night_mode_confidence_metrics AS
SELECT
    COUNT(*) as total_predictions,
    COUNT(actual_outcome) as evaluated_predictions,
    AVG(confidence_score) as avg_confidence,
    AVG(CASE WHEN was_accurate THEN 1.0 ELSE 0.0 END) as accuracy_rate,
    AVG(ABS(confidence_score - CASE WHEN actual_outcome = 'approved' THEN 1.0 ELSE 0.0 END)) as calibration_error,
    COUNT(CASE WHEN confidence_score >= 0.6 THEN 1 END) as high_confidence_count,
    COUNT(CASE WHEN confidence_score < 0.6 THEN 1 END) as low_confidence_count
FROM night_mode_confidence_predictions;

-- View: Factor performance
CREATE OR REPLACE VIEW night_mode_factor_performance AS
SELECT
    c.factor_name,
    c.current_weight,
    c.initial_weight,
    c.weight_adjustment,
    c.calibration_error,
    c.total_predictions,
    c.accurate_predictions,
    CASE
        WHEN c.total_predictions > 0
        THEN c.accurate_predictions::FLOAT / c.total_predictions
        ELSE 0.0
    END as accuracy_rate
FROM night_mode_calibration c;
