-- Migration 123: decision_log outcome tracking fields (runtime compatibility)
-- Adds columns expected by decision_tracker and reflection services.

ALTER TABLE decision_log
    ADD COLUMN
IF NOT EXISTS outcome_score DOUBLE PRECISION,
ADD COLUMN
IF NOT EXISTS outcome_notes TEXT,
ADD COLUMN
IF NOT EXISTS resolved_at TIMESTAMP,
ADD COLUMN
IF NOT EXISTS outcome_verified BOOLEAN DEFAULT FALSE;

CREATE INDEX
IF NOT EXISTS idx_decision_log_outcome_score
    ON decision_log
(outcome_score);

CREATE INDEX
IF NOT EXISTS idx_decision_log_outcome_verified
    ON decision_log
(outcome_verified);
