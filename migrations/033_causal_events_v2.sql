-- Migration: CK02 Causal Event Schema v2
-- Phase: 19.5B
-- Date: 2026-02-05
-- Owner: Codex
-- Parent: 031_causal_events.sql (v1)
--
-- Purpose: Add v2 enhancements to causal_events table:
--   - Priority 1: Causal links (typed relationships)
--   - Priority 2: Outcome quality metrics
--   - Priority 3: Integration fields (task_id, git_commit_hash, proposal_id, phase)
--   - Priority 4: Temporal features (duration, end_timestamp)

-- =============================================================================
-- v2 Priority 1: Causal Links
-- =============================================================================

ALTER TABLE causal_events ADD COLUMN IF NOT EXISTS causal_links JSONB;

-- GIN index for efficient JSONB queries on causal_links
CREATE INDEX IF NOT EXISTS causal_links_gin_idx 
    ON causal_events USING GIN (causal_links);

-- Index for querying by link_type (using JSONB path operator)
CREATE INDEX IF NOT EXISTS causal_links_type_idx 
    ON causal_events USING GIN ((causal_links -> 'link_type'));

-- =============================================================================
-- v2 Priority 2: Outcome Quality Metrics
-- =============================================================================

ALTER TABLE causal_events 
    ADD COLUMN IF NOT EXISTS outcome_success BOOLEAN,
    ADD COLUMN IF NOT EXISTS outcome_quality_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS expected_outcome TEXT,
    ADD COLUMN IF NOT EXISTS deviation_score DOUBLE PRECISION;

-- Index for filtering by outcome success
CREATE INDEX IF NOT EXISTS outcome_success_idx 
    ON causal_events (outcome_success) 
    WHERE outcome_success IS NOT NULL;

-- Index for ordering by quality score (DESC, best first)
CREATE INDEX IF NOT EXISTS outcome_quality_idx 
    ON causal_events (outcome_quality_score DESC NULLS LAST);

-- Index for finding high-deviation events
CREATE INDEX IF NOT EXISTS deviation_score_idx 
    ON causal_events (deviation_score DESC NULLS LAST);

-- =============================================================================
-- v2 Priority 3: Integration Fields
-- =============================================================================

ALTER TABLE causal_events
    ADD COLUMN IF NOT EXISTS task_id TEXT,
    ADD COLUMN IF NOT EXISTS git_commit_hash TEXT,
    ADD COLUMN IF NOT EXISTS proposal_id TEXT,
    ADD COLUMN IF NOT EXISTS phase TEXT;

-- Index for querying events by task
CREATE INDEX IF NOT EXISTS task_id_idx 
    ON causal_events (task_id) 
    WHERE task_id IS NOT NULL;

-- Index for querying events by git commit
CREATE INDEX IF NOT EXISTS git_commit_idx 
    ON causal_events (git_commit_hash) 
    WHERE git_commit_hash IS NOT NULL;

-- Index for querying events by proposal
CREATE INDEX IF NOT EXISTS proposal_id_idx 
    ON causal_events (proposal_id) 
    WHERE proposal_id IS NOT NULL;

-- Index for querying events by phase
CREATE INDEX IF NOT EXISTS phase_idx 
    ON causal_events (phase) 
    WHERE phase IS NOT NULL;

-- =============================================================================
-- v2 Priority 4: Temporal Features
-- =============================================================================

ALTER TABLE causal_events
    ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS end_timestamp TIMESTAMPTZ;

-- Index for querying long-running events
CREATE INDEX IF NOT EXISTS duration_idx 
    ON causal_events (duration_seconds DESC NULLS LAST);

-- GIST index for querying overlapping time ranges
-- Uses PostgreSQL's tstzrange type for efficient temporal queries
CREATE INDEX IF NOT EXISTS time_range_gist_idx 
    ON causal_events USING GIST (
        tstzrange(timestamp, COALESCE(end_timestamp, timestamp))
    );

-- =============================================================================
-- Data Validation Constraints (optional, can be added later)
-- =============================================================================

-- Ensure quality scores are in valid range (0.0-1.0)
ALTER TABLE causal_events 
    ADD CONSTRAINT IF NOT EXISTS outcome_quality_score_range 
    CHECK (outcome_quality_score IS NULL OR (outcome_quality_score >= 0.0 AND outcome_quality_score <= 1.0));

ALTER TABLE causal_events 
    ADD CONSTRAINT IF NOT EXISTS deviation_score_range 
    CHECK (deviation_score IS NULL OR (deviation_score >= 0.0 AND deviation_score <= 1.0));

-- Ensure duration is non-negative
ALTER TABLE causal_events 
    ADD CONSTRAINT IF NOT EXISTS duration_non_negative 
    CHECK (duration_seconds IS NULL OR duration_seconds >= 0.0);

-- Ensure end_timestamp is after start timestamp (if both present)
ALTER TABLE causal_events 
    ADD CONSTRAINT IF NOT EXISTS end_after_start 
    CHECK (end_timestamp IS NULL OR end_timestamp >= timestamp);

-- =============================================================================
-- Migration Complete
-- =============================================================================

-- Verify migration
DO $$ 
BEGIN
    RAISE NOTICE 'CK02 v2 Migration Complete!';
    RAISE NOTICE 'Added columns: causal_links, outcome_success, outcome_quality_score, expected_outcome, deviation_score';
    RAISE NOTICE 'Added columns: task_id, git_commit_hash, proposal_id, phase';
    RAISE NOTICE 'Added columns: duration_seconds, end_timestamp';
    RAISE NOTICE 'Created 14 indexes for efficient queries';
    RAISE NOTICE 'Added 4 data validation constraints';
END $$;
