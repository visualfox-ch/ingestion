-- Migration 131: Agent Delegation Protocol (Phase 22A-09)
-- Enables Jarvis to delegate subtasks to specialist agents

-- Delegation sessions table
CREATE TABLE IF NOT EXISTS jarvis_delegation_sessions (
    id SERIAL PRIMARY KEY,
    original_query TEXT,
    subtask_count INTEGER DEFAULT 0,
    completed_count INTEGER DEFAULT 0,
    integrated_response TEXT,
    status VARCHAR(30) DEFAULT 'active',
    total_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Individual delegations table
CREATE TABLE IF NOT EXISTS jarvis_delegations (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES jarvis_delegation_sessions(id) ON DELETE CASCADE,
    subtask_id VARCHAR(50) NOT NULL,
    description TEXT,
    target_agent VARCHAR(50) NOT NULL,
    context JSONB DEFAULT '{}',
    priority VARCHAR(20) DEFAULT 'normal',
    depends_on JSONB DEFAULT '[]',
    status VARCHAR(30) DEFAULT 'pending',
    result TEXT,
    confidence REAL,
    execution_time_ms INTEGER,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_delegation_sessions_status ON jarvis_delegation_sessions(status);
CREATE INDEX IF NOT EXISTS idx_delegation_sessions_created ON jarvis_delegation_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_delegations_session ON jarvis_delegations(session_id);
CREATE INDEX IF NOT EXISTS idx_delegations_status ON jarvis_delegations(status);
CREATE INDEX IF NOT EXISTS idx_delegations_agent ON jarvis_delegations(target_agent);

-- Comments
COMMENT ON TABLE jarvis_delegation_sessions IS 'Phase 22A-09: Delegation sessions for task decomposition';
COMMENT ON TABLE jarvis_delegations IS 'Phase 22A-09: Individual delegations to specialist agents';
