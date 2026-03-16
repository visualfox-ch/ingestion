-- Migration 032: Fix outcome_known column type from INTEGER to BOOLEAN
-- Problem: CASE/WHEN outcome_known expression fails with type mismatch
--   Error: "argument of CASE/WHEN must be type boolean, not type integer"
--   Location: SELECT COUNT(CASE WHEN outcome_known THEN 1 END) in cross_session_learner.py:427
--
-- Root Cause: outcome_known defined as INTEGER DEFAULT 0 instead of BOOLEAN DEFAULT false
-- Jarvis Impact: Phase 18.2 Cross-Session Learning analytics fail
-- Created: 2026-02-05
-- Owner: Copilot (SQL Schema Fix for Phase 18.2)

BEGIN;

-- Step 1: Check if decision_log table exists and column type
-- Only proceed if table exists (table may not exist on fresh installs)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'decision_log' AND table_schema = 'public'
    ) THEN
        -- Step 2: Add temporary BOOLEAN column
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'decision_log' AND column_name = 'outcome_known_new'
        ) THEN
            ALTER TABLE decision_log ADD COLUMN outcome_known_new BOOLEAN DEFAULT false;
            
            -- Step 3: Migrate data (0 -> false, anything else -> true)
            UPDATE decision_log SET outcome_known_new = (outcome_known::BIGINT > 0::BIGINT);
            
            -- Step 4: Drop old column and rename new one
            ALTER TABLE decision_log DROP COLUMN outcome_known;
            ALTER TABLE decision_log RENAME COLUMN outcome_known_new TO outcome_known;
            
            -- Step 5: Recreate indexes on the fixed column
            DROP INDEX IF EXISTS idx_decisions_user;
            CREATE INDEX idx_decisions_user ON decision_log(user_id, outcome_known);
        END IF;
    END IF;
END $$;

COMMIT;
