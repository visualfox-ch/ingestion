-- Phase 8.1: Multi-Agent Orchestration
-- Created: 2026-02-08
-- Owner: Claude Code
-- Purpose: Enable Jarvis to coordinate with specialized AI agents for complex tasks

-- Agent Registry: Track external AI agents (Claude, Copilot, Codex, custom)
CREATE TABLE IF NOT EXISTS agent_registry (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) UNIQUE NOT NULL,
    agent_name VARCHAR(255) NOT NULL,
    agent_type VARCHAR(50) NOT NULL,  -- claude, copilot, codex, custom, jarvis
    description TEXT,
    capabilities JSONB DEFAULT '[]',
    specializations JSONB DEFAULT '[]',
    endpoint_url TEXT,
    auth_method VARCHAR(50),  -- api_key, oauth, none
    auth_config JSONB DEFAULT '{}',  -- encrypted credentials reference
    status VARCHAR(20) DEFAULT 'active',  -- active, inactive, maintenance, error
    health_status VARCHAR(20) DEFAULT 'unknown',  -- healthy, degraded, unhealthy, unknown
    last_health_check TIMESTAMPTZ,
    avg_response_time_ms FLOAT,
    success_rate FLOAT,
    total_tasks_completed INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent Tasks: Track tasks assigned to agents
CREATE TABLE IF NOT EXISTS agent_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(100) UNIQUE NOT NULL,
    parent_task_id VARCHAR(100),  -- For subtasks
    root_task_id VARCHAR(100),    -- Original task that spawned this
    assigned_agent_id VARCHAR(100) REFERENCES agent_registry(agent_id),
    requested_by VARCHAR(100),    -- User or agent that requested this
    task_type VARCHAR(100) NOT NULL,  -- code_review, research, analysis, generation, etc.
    priority VARCHAR(20) DEFAULT 'normal',  -- low, normal, high, critical
    input_data JSONB NOT NULL,
    output_data JSONB,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, queued, in_progress, completed, failed, cancelled
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 300,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms FLOAT,
    tokens_used INTEGER,
    cost_estimate FLOAT,
    quality_score FLOAT,  -- 0-1 based on validation/feedback
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent Communications: Log all inter-agent messages
CREATE TABLE IF NOT EXISTS agent_communications (
    id SERIAL PRIMARY KEY,
    communication_id VARCHAR(100) UNIQUE NOT NULL,
    from_agent VARCHAR(100) NOT NULL,  -- Can be 'user' for human-initiated
    to_agent VARCHAR(100) NOT NULL,
    task_id VARCHAR(100) REFERENCES agent_tasks(task_id),
    message_type VARCHAR(50) NOT NULL,  -- request, response, stream, error, heartbeat
    payload JSONB NOT NULL,
    response JSONB,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, delivered, acknowledged, failed
    latency_ms FLOAT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ
);

-- Task Decomposition: Track how complex tasks are broken down
CREATE TABLE IF NOT EXISTS task_decompositions (
    id SERIAL PRIMARY KEY,
    decomposition_id VARCHAR(100) UNIQUE NOT NULL,
    original_task_id VARCHAR(100) NOT NULL,
    original_description TEXT NOT NULL,
    strategy VARCHAR(50) NOT NULL,  -- parallel, sequential, hybrid, adaptive
    subtasks JSONB NOT NULL,  -- Array of {task_id, description, dependencies, assigned_agent}
    dependency_graph JSONB,   -- DAG of task dependencies
    status VARCHAR(20) DEFAULT 'active',  -- active, completed, failed, cancelled
    total_subtasks INTEGER,
    completed_subtasks INTEGER DEFAULT 0,
    aggregation_strategy VARCHAR(50),  -- merge, vote, best, weighted
    final_result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Agent Capabilities: Detailed capability definitions
CREATE TABLE IF NOT EXISTS agent_capabilities (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agent_registry(agent_id),
    capability_name VARCHAR(100) NOT NULL,
    capability_type VARCHAR(50) NOT NULL,  -- language, task, domain, integration
    proficiency_score FLOAT DEFAULT 0.5,  -- 0-1, how good at this capability
    examples JSONB DEFAULT '[]',
    limitations TEXT,
    cost_per_use FLOAT,
    avg_duration_ms FLOAT,
    success_rate FLOAT,
    last_used_at TIMESTAMPTZ,
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agent_id, capability_name)
);

-- Agent Health History: Track agent health over time
CREATE TABLE IF NOT EXISTS agent_health_history (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) REFERENCES agent_registry(agent_id),
    check_type VARCHAR(50) NOT NULL,  -- ping, task_test, load_test
    status VARCHAR(20) NOT NULL,  -- healthy, degraded, unhealthy
    response_time_ms FLOAT,
    error_message TEXT,
    details JSONB,
    checked_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent ON agent_tasks(assigned_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_parent ON agent_tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_root ON agent_tasks(root_task_id);
CREATE INDEX IF NOT EXISTS idx_agent_communications_task ON agent_communications(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_communications_from ON agent_communications(from_agent);
CREATE INDEX IF NOT EXISTS idx_agent_communications_to ON agent_communications(to_agent);
CREATE INDEX IF NOT EXISTS idx_task_decompositions_original ON task_decompositions(original_task_id);
CREATE INDEX IF NOT EXISTS idx_agent_capabilities_type ON agent_capabilities(capability_type);
CREATE INDEX IF NOT EXISTS idx_agent_health_history_agent ON agent_health_history(agent_id, checked_at DESC);

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_agent_registry_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_agent_registry_updated_at
    BEFORE UPDATE ON agent_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_registry_timestamp();
