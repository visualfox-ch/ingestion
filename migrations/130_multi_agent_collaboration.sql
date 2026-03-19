-- Migration 130: Multi-Agent Collaboration (Phase 22A-08)
-- Enables multiple agents to collaborate on complex tasks

-- Collaborations table (tracks multi-agent sessions)
CREATE TABLE IF NOT EXISTS jarvis_collaborations (
    id SERIAL PRIMARY KEY,
    collaboration_type VARCHAR(30) NOT NULL,  -- parallel, sequential, primary_secondary
    agents JSONB NOT NULL,
    original_query TEXT,
    synthesized_response TEXT,
    total_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Collaboration results table (individual agent contributions)
CREATE TABLE IF NOT EXISTS jarvis_collaboration_results (
    id SERIAL PRIMARY KEY,
    collaboration_id INTEGER REFERENCES jarvis_collaborations(id) ON DELETE CASCADE,
    agent_name VARCHAR(50) NOT NULL,
    success BOOLEAN DEFAULT TRUE,
    content TEXT,
    confidence REAL,
    tools_used JSONB DEFAULT '[]'::jsonb,
    execution_time_ms INTEGER,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_collaborations_type ON jarvis_collaborations(collaboration_type);
CREATE INDEX IF NOT EXISTS idx_collaborations_created ON jarvis_collaborations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collaboration_results_collab ON jarvis_collaboration_results(collaboration_id);

-- Comments
COMMENT ON TABLE jarvis_collaborations IS 'Phase 22A-08: Multi-agent collaboration sessions';
COMMENT ON TABLE jarvis_collaboration_results IS 'Phase 22A-08: Individual agent contributions to collaborations';
