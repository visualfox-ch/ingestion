-- Pillar 6: Self-Optimization Loop
-- Phase 2D.6 (Feb 24 - Mar 7, 2026)
-- Created: 2026-02-05
--
-- Tracks:
-- 1. Interaction metrics (effectiveness scoring)
-- 2. Self-optimization improvements applied
-- 3. Learning episodes (how Jarvis learns)
-- 4. System prompt evolution history
-- 5. Performance improvement measurements

CREATE TABLE IF NOT EXISTS jarvis_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255),
    session_id VARCHAR(255),
    message_type VARCHAR(50),              -- 'advice', 'question', 'summary', 'brainstorm', etc.
    domain VARCHAR(50),                    -- 'coding', 'business', 'life', 'creative', etc.
    effectiveness_score FLOAT,             -- 0.0-1.0, derived from user feedback or post-interaction analysis
    user_satisfaction FLOAT,               -- optional survey response (0.0-1.0)
    duration_seconds FLOAT,                -- how long the interaction took
    tokens_used INTEGER,                   -- LLM tokens consumed
    tool_used VARCHAR(255),                -- primary tool name used (if any)
    reasoning_path TEXT,                   -- summary of thinking/reasoning
    user_feedback TEXT,                    -- user's direct feedback (if provided)
    is_successful BOOLEAN DEFAULT NULL,    -- explicit success/failure marking
    INDEX idx_created_at (created_at),
    INDEX idx_domain_effectiveness (domain, effectiveness_score),
    INDEX idx_user_domain_ts (user_id, domain, created_at),
    INDEX idx_message_type (message_type)
);

CREATE TABLE IF NOT EXISTS jarvis_self_optimizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    improvement_type VARCHAR(100),         -- 'prompt_change', 'tool_addition', 'behavior_modification', etc.
    description TEXT NOT NULL,             -- what improvement was made
    rationale TEXT,                        -- why this improvement was suggested
    expected_impact FLOAT,                 -- predicted effectiveness gain (e.g., 0.08 = +8%)
    actual_impact FLOAT,                   -- measured effectiveness gain (calculated later)
    effectiveness_before FLOAT,            -- baseline effectiveness at time of change
    effectiveness_after FLOAT,             -- measured effectiveness after change
    applied_at TIMESTAMP,                  -- when the improvement was actually applied
    rolled_back_at TIMESTAMP,              -- if improvement was reverted
    rollback_reason TEXT,                  -- why it was rolled back
    priority VARCHAR(20),                  -- 'HIGH', 'MEDIUM', 'LOW'
    status VARCHAR(50) DEFAULT 'proposed', -- 'proposed', 'approved', 'applied', 'rolled_back'
    test_window_days INTEGER DEFAULT 7,    -- how many days to measure impact over
    INDEX idx_status (status),
    INDEX idx_applied_at (applied_at),
    INDEX idx_created_at (created_at)
);

CREATE TABLE IF NOT EXISTS jarvis_learning_episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    input_type VARCHAR(50),                -- 'example', 'principle', 'feedback', 'conversation', 'failure'
    topic TEXT,                            -- what subject was learned
    effectiveness_before FLOAT,            -- effectiveness score on this topic before learning
    effectiveness_after FLOAT,             -- effectiveness score after learning
    time_to_mastery_minutes FLOAT,         -- how long it took to understand
    retention_days_later FLOAT,            -- how much improvement persisted N days later
    retention_measured_at TIMESTAMP,       -- when retention was measured
    learning_quality FLOAT,                -- human assessment of learning quality (0-1)
    INDEX idx_input_type (input_type),
    INDEX idx_created_at (created_at),
    INDEX idx_effectiveness_after (effectiveness_after)
);

CREATE TABLE IF NOT EXISTS jarvis_system_prompt_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL,              -- semantic version of prompt
    prompt_text TEXT NOT NULL,             -- full system prompt
    source VARCHAR(100),                   -- 'manual', 'self_optimization', 'feedback', etc.
    effectiveness_before FLOAT,            -- effectiveness score when this version was deployed
    effectiveness_after FLOAT,             -- measured effectiveness after
    description TEXT,                      -- human-readable summary of changes
    active_until TIMESTAMP,                -- when this version was replaced
    rollback_to_at TIMESTAMP,              -- if this version was restored after rollback
    INDEX idx_created_at (created_at),
    INDEX idx_version (version)
);

CREATE TABLE IF NOT EXISTS jarvis_performance_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    window_days INTEGER,                   -- analysis window (e.g., 7 = last 7 days)
    analysis_data JSONB,                   -- full analysis result
    average_effectiveness FLOAT,
    highest_impact_domains JSONB,          -- [{domain, score}, ...]
    blind_spots JSONB,                     -- [{domain, score}, ...]
    most_successful_patterns JSONB,        -- patterns that worked well
    failure_modes JSONB,                   -- anti-patterns that failed
    recommended_improvements JSONB,        -- list of suggested improvements
    INDEX idx_created_at (created_at),
    INDEX idx_window_days (window_days)
);

-- Table to store meta-learning insights
CREATE TABLE IF NOT EXISTS jarvis_meta_learning_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    learning_style VARCHAR(255),           -- e.g., 'Case-by-Case Socratic'
    key_patterns JSONB,                    -- list of learned patterns
    optimal_teaching_method TEXT,          -- derived teaching methodology
    effectiveness_multiplier FLOAT,        -- how much better vs worst approach
    recommended_teaching_approach JSONB,   -- {steps, cadence, success_metric}
    INDEX idx_created_at (created_at)
);

-- Idempotent: ensure all necessary indexes exist
CREATE INDEX IF NOT EXISTS idx_interactions_user_ts 
  ON jarvis_interactions(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_optimizations_applied 
  ON jarvis_self_optimizations(applied_at DESC) 
  WHERE status = 'applied';

CREATE INDEX IF NOT EXISTS idx_learning_effectiveness_trend 
  ON jarvis_learning_episodes(created_at DESC, effectiveness_after);

-- Add column to jarvis_interactions if not exists (in case of earlier partial migration)
ALTER TABLE IF EXISTS jarvis_interactions 
  ADD COLUMN IF NOT EXISTS is_successful BOOLEAN DEFAULT NULL;

ALTER TABLE IF EXISTS jarvis_interactions 
  ADD COLUMN IF NOT EXISTS user_feedback TEXT;
