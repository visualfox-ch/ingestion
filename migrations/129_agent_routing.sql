-- Phase 22A-07: Intent-Based Agent Routing
-- Date: 2026-03-19
-- Task: T-22A-07

-- =============================================================================
-- Routing Decisions (tracking routing strategy and agent selection)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_routing_decisions (
    id SERIAL PRIMARY KEY,
    query_hash VARCHAR(32),
    strategy VARCHAR(20),               -- single, multi, core, forced
    primary_agent VARCHAR(50),
    secondary_agents JSONB DEFAULT '[]',
    confidence REAL,
    intent_scores JSONB,                -- {fitness: 0.8, work: 0.2, ...}
    routing_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_decisions_strategy
ON jarvis_routing_decisions(strategy);

CREATE INDEX IF NOT EXISTS idx_routing_decisions_agent
ON jarvis_routing_decisions(primary_agent);

CREATE INDEX IF NOT EXISTS idx_routing_decisions_created
ON jarvis_routing_decisions(created_at DESC);

-- =============================================================================
-- Routing Outcomes (for learning and optimization)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_routing_outcomes (
    id SERIAL PRIMARY KEY,
    routing_id INTEGER REFERENCES jarvis_routing_decisions(id),
    agents_executed JSONB,              -- [{agent: "fit_jarvis", time_ms: 100, success: true}]
    total_time_ms INTEGER,
    success BOOLEAN,
    user_satisfaction VARCHAR(20),      -- great, good, ok, poor, none
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_outcomes_routing
ON jarvis_routing_outcomes(routing_id);

CREATE INDEX IF NOT EXISTS idx_routing_outcomes_satisfaction
ON jarvis_routing_outcomes(user_satisfaction) WHERE user_satisfaction IS NOT NULL;

-- =============================================================================
-- Intent Patterns (configurable domain patterns)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_intent_patterns (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(50) NOT NULL,        -- fitness, work, communication, general
    pattern_type VARCHAR(30),           -- keyword, regex, context
    pattern_value TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intent_patterns_domain
ON jarvis_intent_patterns(domain) WHERE enabled = TRUE;

-- Seed default intent patterns (can be extended by Jarvis)
INSERT INTO jarvis_intent_patterns (domain, pattern_type, pattern_value, weight) VALUES
    -- Fitness patterns
    ('fitness', 'keyword', 'workout', 1.0),
    ('fitness', 'keyword', 'exercise', 1.0),
    ('fitness', 'keyword', 'training', 1.0),
    ('fitness', 'keyword', 'calories', 0.8),
    ('fitness', 'keyword', 'protein', 0.8),
    ('fitness', 'keyword', 'gym', 1.0),
    ('fitness', 'keyword', 'run', 0.7),
    ('fitness', 'keyword', 'fitness', 1.0),

    -- Work patterns
    ('work', 'keyword', 'task', 1.0),
    ('work', 'keyword', 'project', 1.0),
    ('work', 'keyword', 'deadline', 1.0),
    ('work', 'keyword', 'meeting', 0.8),
    ('work', 'keyword', 'focus', 0.9),
    ('work', 'keyword', 'productivity', 1.0),
    ('work', 'keyword', 'estimate', 0.8),

    -- Communication patterns
    ('communication', 'keyword', 'email', 1.0),
    ('communication', 'keyword', 'message', 0.9),
    ('communication', 'keyword', 'reply', 1.0),
    ('communication', 'keyword', 'contact', 0.8),
    ('communication', 'keyword', 'followup', 1.0),
    ('communication', 'keyword', 'inbox', 1.0),
    ('communication', 'keyword', 'draft', 0.9)
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Agent Routing Preferences (user-specific routing rules)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_routing_preferences (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    preference_type VARCHAR(50),        -- default_agent, domain_override, time_based
    preference_data JSONB NOT NULL,
    priority INTEGER DEFAULT 100,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_preferences_user
ON jarvis_routing_preferences(user_id) WHERE enabled = TRUE;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE jarvis_routing_decisions IS 'Phase 22A-07: Agent routing decision tracking';
COMMENT ON TABLE jarvis_routing_outcomes IS 'Phase 22A-07: Routing outcome tracking for learning';
COMMENT ON TABLE jarvis_intent_patterns IS 'Phase 22A-07: Configurable intent patterns per domain';
COMMENT ON TABLE jarvis_routing_preferences IS 'Phase 22A-07: User-specific routing preferences';
