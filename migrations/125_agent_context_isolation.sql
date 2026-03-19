-- Phase 22A-03: Agent Context Isolation
-- Date: 2026-03-19
-- Task: T-22A-03

-- =============================================================================
-- Agent Context Storage (per-session isolated context)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_agent_contexts (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    context_key VARCHAR(100) NOT NULL,
    context_value JSONB NOT NULL,
    sharing_policy VARCHAR(20) DEFAULT 'private',  -- private, domain, cross, public
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, session_id, context_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_contexts_agent_session
ON jarvis_agent_contexts(agent_id, session_id);

CREATE INDEX IF NOT EXISTS idx_agent_contexts_sharing
ON jarvis_agent_contexts(sharing_policy) WHERE sharing_policy != 'private';

-- =============================================================================
-- Cross-Agent Boundaries (data sharing rules)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_agent_boundaries (
    id SERIAL PRIMARY KEY,
    source_agent VARCHAR(50) NOT NULL,
    target_agent VARCHAR(50) NOT NULL,
    data_types JSONB DEFAULT '[]',
    direction VARCHAR(10) DEFAULT 'read',  -- read, write, both
    requires_approval BOOLEAN DEFAULT TRUE,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_agent, target_agent)
);

CREATE INDEX IF NOT EXISTS idx_agent_boundaries_source
ON jarvis_agent_boundaries(source_agent) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_agent_boundaries_target
ON jarvis_agent_boundaries(target_agent) WHERE active = TRUE;

-- =============================================================================
-- Isolated Agent Memory (namespace-based memory storage)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_agent_memory (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    namespace VARCHAR(100) NOT NULL,
    memory_key VARCHAR(200) NOT NULL,
    memory_value JSONB NOT NULL,
    memory_type VARCHAR(50) DEFAULT 'fact',  -- fact, preference, goal, observation
    confidence FLOAT DEFAULT 0.8,
    access_count INTEGER DEFAULT 0,
    sharing_policy VARCHAR(20) DEFAULT 'private',
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, namespace, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_namespace
ON jarvis_agent_memory(agent_id, namespace);

CREATE INDEX IF NOT EXISTS idx_agent_memory_type
ON jarvis_agent_memory(memory_type);

CREATE INDEX IF NOT EXISTS idx_agent_memory_sharing
ON jarvis_agent_memory(sharing_policy) WHERE sharing_policy != 'private';

-- =============================================================================
-- Default Boundaries: Allow fitness/work/comm agents to share insights
-- =============================================================================

INSERT INTO jarvis_agent_boundaries (source_agent, target_agent, data_types, direction, requires_approval)
VALUES
    ('fit_jarvis', 'work_jarvis', '["energy_level", "workout_schedule"]', 'read', FALSE),
    ('work_jarvis', 'fit_jarvis', '["work_schedule", "stress_level"]', 'read', FALSE),
    ('fit_jarvis', 'comm_jarvis', '["activity_status"]', 'read', FALSE),
    ('work_jarvis', 'comm_jarvis', '["availability", "focus_mode"]', 'read', FALSE)
ON CONFLICT (source_agent, target_agent) DO NOTHING;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE jarvis_agent_contexts IS 'Phase 22A-03: Per-session isolated context for specialist agents';
COMMENT ON TABLE jarvis_agent_boundaries IS 'Phase 22A-03: Cross-agent data sharing boundaries';
COMMENT ON TABLE jarvis_agent_memory IS 'Phase 22A-03: Namespace-isolated memory for specialist agents';
COMMENT ON COLUMN jarvis_agent_contexts.sharing_policy IS 'private=only this agent, domain=same domain, cross=all agents, public=unrestricted';
