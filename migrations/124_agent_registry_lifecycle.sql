-- Phase 22A-02: Agent Registry & Lifecycle
-- Date: 2026-03-19
-- Task: T-22A-02

-- =============================================================================
-- Extend jarvis_specialist_agents with lifecycle columns
-- =============================================================================

-- Add state column for lifecycle management
ALTER TABLE jarvis_specialist_agents
ADD COLUMN IF NOT EXISTS state VARCHAR(20) DEFAULT 'active';

-- Add dependencies column (list of agent_ids this agent depends on)
ALTER TABLE jarvis_specialist_agents
ADD COLUMN IF NOT EXISTS dependencies JSONB DEFAULT '[]';

-- Add error tracking columns
ALTER TABLE jarvis_specialist_agents
ADD COLUMN IF NOT EXISTS error_count INTEGER DEFAULT 0;

ALTER TABLE jarvis_specialist_agents
ADD COLUMN IF NOT EXISTS last_error TEXT;

ALTER TABLE jarvis_specialist_agents
ADD COLUMN IF NOT EXISTS last_health_check TIMESTAMP;

-- Create index on state for faster lifecycle queries
CREATE INDEX IF NOT EXISTS idx_specialist_agents_state
ON jarvis_specialist_agents(state);

-- =============================================================================
-- Agent lifecycle history for auditing
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_agent_lifecycle_events (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(30) NOT NULL,  -- registered, started, stopped, paused, resumed, error, reset
    old_state VARCHAR(20),
    new_state VARCHAR(20),
    reason TEXT,
    triggered_by VARCHAR(50),  -- user, system, dependency
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_events_agent
ON jarvis_agent_lifecycle_events(agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lifecycle_events_type
ON jarvis_agent_lifecycle_events(event_type);

-- =============================================================================
-- Update existing agents to have proper state
-- =============================================================================

UPDATE jarvis_specialist_agents
SET state = CASE WHEN active = TRUE THEN 'active' ELSE 'stopped' END
WHERE state IS NULL;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON COLUMN jarvis_specialist_agents.state IS 'Lifecycle state: registered, initializing, active, paused, stopped, error, maintenance';
COMMENT ON COLUMN jarvis_specialist_agents.dependencies IS 'Array of agent_ids this agent depends on';
COMMENT ON COLUMN jarvis_specialist_agents.error_count IS 'Consecutive error count for health tracking';
COMMENT ON COLUMN jarvis_specialist_agents.last_error IS 'Last error message';
COMMENT ON COLUMN jarvis_specialist_agents.last_health_check IS 'Timestamp of last health check';
COMMENT ON TABLE jarvis_agent_lifecycle_events IS 'Phase 22A-02: Agent lifecycle event history for auditing';
