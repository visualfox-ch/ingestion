-- Phase 22 Quick Wins: Emergent Intelligence Foundation
-- Date: 2026-03-19
-- Tasks: T-22A-01, T-22B-01, T-22C-01, T-22D-01

-- =============================================================================
-- T-22A-01: Specialist Agent Registry (extends existing jarvis_specialists)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_specialist_agents (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) UNIQUE NOT NULL,
    domain VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    tools JSONB DEFAULT '[]',
    identity_extension JSONB DEFAULT '{}',
    memory_namespace VARCHAR(100),
    confidence_threshold FLOAT DEFAULT 0.7,
    active BOOLEAN DEFAULT TRUE,
    activation_count INTEGER DEFAULT 0,
    last_activated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_specialist_agents_domain
ON jarvis_specialist_agents(domain);

CREATE INDEX IF NOT EXISTS idx_specialist_agents_active
ON jarvis_specialist_agents(active) WHERE active = TRUE;

-- =============================================================================
-- T-22B-01: Agent Messages (extends jarvis_agent_handoffs)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_agent_messages (
    id SERIAL PRIMARY KEY,
    message_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    from_agent VARCHAR(50) NOT NULL,
    to_agent VARCHAR(50),  -- NULL for broadcasts
    message_type VARCHAR(20) NOT NULL,  -- request, response, broadcast, handoff, notification
    subject VARCHAR(200),
    content JSONB NOT NULL,
    priority VARCHAR(10) DEFAULT 'normal',  -- low, normal, high, urgent
    status VARCHAR(20) DEFAULT 'pending',  -- pending, delivered, read, processed, expired
    reply_to_id UUID,  -- Links to original message
    session_id VARCHAR(100),
    user_id VARCHAR(100),
    related_query TEXT,
    metadata JSONB DEFAULT '{}',
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_to_agent
ON jarvis_agent_messages(to_agent, status);

CREATE INDEX IF NOT EXISTS idx_agent_messages_from_agent
ON jarvis_agent_messages(from_agent);

CREATE INDEX IF NOT EXISTS idx_agent_messages_type
ON jarvis_agent_messages(message_type);

CREATE INDEX IF NOT EXISTS idx_agent_messages_reply
ON jarvis_agent_messages(reply_to_id) WHERE reply_to_id IS NOT NULL;

-- =============================================================================
-- T-22C-01: Abstract Patterns (Cross-Domain Learning)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_abstract_patterns (
    id SERIAL PRIMARY KEY,
    pattern_id VARCHAR(50) UNIQUE NOT NULL,
    abstract_form TEXT NOT NULL,
    source_domains JSONB DEFAULT '[]',
    evidence_count INTEGER DEFAULT 0,
    confidence FLOAT DEFAULT 0.5,
    applicable_domains JSONB DEFAULT '[]',
    source_pattern_ids JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    last_validated_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_abstract_patterns_confidence
ON jarvis_abstract_patterns(confidence DESC);

CREATE INDEX IF NOT EXISTS idx_abstract_patterns_domains
ON jarvis_abstract_patterns USING GIN (source_domains);

CREATE INDEX IF NOT EXISTS idx_abstract_patterns_applicable
ON jarvis_abstract_patterns USING GIN (applicable_domains);

-- Knowledge Transfers
CREATE TABLE IF NOT EXISTS jarvis_knowledge_transfers (
    id SERIAL PRIMARY KEY,
    source_pattern_id INTEGER,
    abstract_pattern_id VARCHAR(50),
    source_domain VARCHAR(50),
    target_domain VARCHAR(50) NOT NULL,
    transfer_confidence FLOAT DEFAULT 0.5,
    validation_attempts INTEGER DEFAULT 0,
    validation_successes INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, validated, rejected, testing
    created_at TIMESTAMP DEFAULT NOW(),
    last_tested_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_knowledge_transfers_status
ON jarvis_knowledge_transfers(status);

CREATE INDEX IF NOT EXISTS idx_knowledge_transfers_domain
ON jarvis_knowledge_transfers(target_domain);

-- =============================================================================
-- T-22D-01: Goals and Tasks (extends existing jarvis_goals)
-- =============================================================================

-- Add goal_id UUID column if not exists (for Phase 22D compatibility)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jarvis_goals' AND column_name = 'goal_id'
    ) THEN
        ALTER TABLE jarvis_goals ADD COLUMN goal_id UUID DEFAULT gen_random_uuid();
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jarvis_goals_uuid ON jarvis_goals(goal_id);
    END IF;
END $$;

-- Goal Tasks (sub-tasks within goals)
CREATE TABLE IF NOT EXISTS jarvis_goal_tasks (
    id SERIAL PRIMARY KEY,
    task_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    goal_id UUID,  -- References jarvis_goals.goal_id
    assigned_agent VARCHAR(50),
    title TEXT NOT NULL,
    description TEXT,
    prerequisites JSONB DEFAULT '[]',  -- Other task_ids that must complete first
    status VARCHAR(20) DEFAULT 'pending',  -- pending, in_progress, completed, blocked, skipped
    priority INTEGER DEFAULT 100,
    progress_pct INTEGER DEFAULT 0,
    output JSONB,
    estimated_minutes INTEGER,
    actual_minutes INTEGER,
    blocked_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goal_tasks_goal
ON jarvis_goal_tasks(goal_id);

CREATE INDEX IF NOT EXISTS idx_goal_tasks_status
ON jarvis_goal_tasks(status);

CREATE INDEX IF NOT EXISTS idx_goal_tasks_agent
ON jarvis_goal_tasks(assigned_agent);

-- =============================================================================
-- Seed Data: Default Specialist Agents
-- =============================================================================

INSERT INTO jarvis_specialist_agents (agent_id, domain, display_name, tools, identity_extension, memory_namespace)
VALUES
    ('fit_jarvis', 'fitness', 'FitJarvis',
     '["log_workout", "get_fitness_trends", "track_nutrition", "suggest_exercise"]'::jsonb,
     '{"expertise": ["fitness", "nutrition", "health"], "communication_style": "motivating", "traits": {"energy": "high", "focus": "results"}}'::jsonb,
     'fitness'),
    ('work_jarvis', 'work', 'WorkJarvis',
     '["prioritize_tasks", "estimate_effort", "track_focus_time", "suggest_breaks"]'::jsonb,
     '{"expertise": ["productivity", "project management", "time management"], "communication_style": "efficient", "traits": {"energy": "focused", "focus": "efficiency"}}'::jsonb,
     'work'),
    ('comm_jarvis', 'communication', 'CommJarvis',
     '["triage_inbox", "draft_response", "track_relationship", "schedule_followup"]'::jsonb,
     '{"expertise": ["communication", "networking", "relationship management"], "communication_style": "empathetic", "traits": {"energy": "warm", "focus": "relationships"}}'::jsonb,
     'communication')
ON CONFLICT (agent_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    tools = EXCLUDED.tools,
    identity_extension = EXCLUDED.identity_extension,
    updated_at = NOW();

-- =============================================================================
-- Views for Monitoring
-- =============================================================================

CREATE OR REPLACE VIEW v_phase22_status AS
SELECT
    'specialist_agents' as component,
    (SELECT COUNT(*) FROM jarvis_specialist_agents WHERE active = TRUE) as active_count,
    (SELECT COUNT(*) FROM jarvis_specialist_agents) as total_count
UNION ALL
SELECT
    'agent_messages',
    (SELECT COUNT(*) FROM jarvis_agent_messages WHERE status = 'pending'),
    (SELECT COUNT(*) FROM jarvis_agent_messages)
UNION ALL
SELECT
    'abstract_patterns',
    (SELECT COUNT(*) FROM jarvis_abstract_patterns WHERE confidence >= 0.6),
    (SELECT COUNT(*) FROM jarvis_abstract_patterns)
UNION ALL
SELECT
    'knowledge_transfers',
    (SELECT COUNT(*) FROM jarvis_knowledge_transfers WHERE status = 'validated'),
    (SELECT COUNT(*) FROM jarvis_knowledge_transfers)
UNION ALL
SELECT
    'goal_tasks',
    (SELECT COUNT(*) FROM jarvis_goal_tasks WHERE status = 'in_progress'),
    (SELECT COUNT(*) FROM jarvis_goal_tasks);

COMMENT ON TABLE jarvis_specialist_agents IS 'Phase 22A: Domain specialist agent registry';
COMMENT ON TABLE jarvis_agent_messages IS 'Phase 22B: Inter-agent communication messages';
COMMENT ON TABLE jarvis_abstract_patterns IS 'Phase 22C: Domain-agnostic patterns for cross-domain learning';
COMMENT ON TABLE jarvis_knowledge_transfers IS 'Phase 22C: Pattern transfer attempts between domains';
COMMENT ON TABLE jarvis_goal_tasks IS 'Phase 22D: Sub-tasks within goals for decomposition';
