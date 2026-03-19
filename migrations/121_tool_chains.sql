-- Migration: Tool Chains System
-- Phase 21A: Smart Tool Chains
-- Date: 2026-03-18

-- Table for storing tool chain rules
CREATE TABLE IF NOT EXISTS jarvis_tool_chains (
    id SERIAL PRIMARY KEY,
    trigger_tool VARCHAR(100) NOT NULL,
    follow_up_tool VARCHAR(100) NOT NULL,
    condition VARCHAR(100) DEFAULT 'on_success',
    priority INTEGER DEFAULT 50,
    description TEXT,
    enabled BOOLEAN DEFAULT true,
    execution_count INTEGER DEFAULT 0,
    last_executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(trigger_tool, follow_up_tool)
);

CREATE INDEX IF NOT EXISTS idx_tool_chains_trigger ON jarvis_tool_chains(trigger_tool);
CREATE INDEX IF NOT EXISTS idx_tool_chains_enabled ON jarvis_tool_chains(enabled);

-- Table for logging chain executions
CREATE TABLE IF NOT EXISTS jarvis_tool_chain_executions (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER REFERENCES jarvis_tool_chains(id),
    trigger_tool VARCHAR(100) NOT NULL,
    follow_up_tool VARCHAR(100) NOT NULL,
    trigger_result JSONB,
    follow_up_result JSONB,
    success BOOLEAN,
    latency_ms INTEGER,
    session_id VARCHAR(100),
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chain_exec_time ON jarvis_tool_chain_executions(executed_at DESC);

-- Insert default chains
INSERT INTO jarvis_tool_chains (trigger_tool, follow_up_tool, condition, priority, description) VALUES
('remember_fact', 'check_fact_duplicates', 'on_success', 50, 'Check for duplicate facts after storing'),
('search_knowledge', 'rank_search_results', 'result_count > 5', 40, 'Rank results when too many returned'),
('create_action_plan', 'estimate_plan_complexity', 'on_success', 50, 'Estimate complexity after creating plan'),
('run_safe_playbook', 'verify_playbook_success', 'on_success', 60, 'Verify playbook completed successfully'),
('record_learning', 'check_learning_conflicts', 'on_success', 50, 'Check for conflicting learnings'),
('store_context', 'summarize_context_delta', 'context_size > 1000', 30, 'Summarize large context additions'),
('send_email', 'log_communication', 'on_success', 40, 'Log sent communications'),
('create_calendar_event', 'check_calendar_conflicts', 'on_success', 50, 'Check for scheduling conflicts')
ON CONFLICT (trigger_tool, follow_up_tool) DO NOTHING;

-- Comments
COMMENT ON TABLE jarvis_tool_chains IS 'Phase 21A: Automatic tool follow-up rules';
COMMENT ON TABLE jarvis_tool_chain_executions IS 'Phase 21A: Log of chain executions for analysis';
