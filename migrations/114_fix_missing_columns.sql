-- Migration 114: Fix missing columns
-- Adds columns that services expect but don't exist

-- 1. Add query_hash to decision_log (used by decision_tracker.py)
ALTER TABLE decision_log
ADD COLUMN IF NOT EXISTS query_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_decision_log_query_hash
ON decision_log(query_hash);

-- 2. Add progress_percentage to jarvis_goals (used by specialist_agent_service.py)
-- Calculated as (current_value / target_value * 100), defaults to 0
ALTER TABLE jarvis_goals
ADD COLUMN IF NOT EXISTS progress_percentage REAL DEFAULT 0;

-- Update existing goals with calculated progress
UPDATE jarvis_goals
SET progress_percentage = CASE
    WHEN target_value IS NOT NULL AND target_value > 0
    THEN LEAST((current_value / target_value) * 100, 100)
    ELSE 0
END
WHERE progress_percentage = 0 OR progress_percentage IS NULL;

-- 3. Add missing columns to jarvis_specialist_activations (if needed)
ALTER TABLE jarvis_specialist_activations
ADD COLUMN IF NOT EXISTS query_hash VARCHAR(32);

COMMENT ON COLUMN decision_log.query_hash IS 'MD5 hash of query for deduplication';
COMMENT ON COLUMN jarvis_goals.progress_percentage IS 'Progress towards goal (0-100)';
