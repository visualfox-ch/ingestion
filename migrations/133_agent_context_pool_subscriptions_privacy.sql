-- Migration 133: Agent Context Pool + Subscriptions + Privacy Boundaries (Phase 22B-04/05/06)

-- Shared context entries visible across agents according to visibility rules
CREATE TABLE IF NOT EXISTS jarvis_shared_context_pool (
    id SERIAL PRIMARY KEY,
    context_id VARCHAR(50) UNIQUE NOT NULL,
    source_agent VARCHAR(50) NOT NULL,
    context_key VARCHAR(120) NOT NULL,
    context_value JSONB NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'domain', -- global, domain, private, temporary
    domain VARCHAR(50),
    tags JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    session_id VARCHAR(100),
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Per-agent subscription profile for context updates
CREATE TABLE IF NOT EXISTS jarvis_context_subscriptions (
    id SERIAL PRIMARY KEY,
    subscription_id VARCHAR(50) UNIQUE NOT NULL,
    agent_id VARCHAR(50) NOT NULL,
    visibility_levels JSONB DEFAULT '["global", "domain"]'::jsonb,
    domains JSONB DEFAULT '[]'::jsonb,
    source_agents JSONB DEFAULT '[]'::jsonb,
    tags JSONB DEFAULT '[]'::jsonb,
    include_temporary BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id)
);

-- Explicit source->target privacy boundaries for shared context visibility
CREATE TABLE IF NOT EXISTS jarvis_context_privacy_boundaries (
    id SERIAL PRIMARY KEY,
    source_agent VARCHAR(50) NOT NULL,
    target_agent VARCHAR(50) NOT NULL,
    allowed_levels JSONB DEFAULT '["global", "domain"]'::jsonb,
    allowed_keys JSONB DEFAULT '[]'::jsonb,
    denied_keys JSONB DEFAULT '[]'::jsonb,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_agent, target_agent)
);

CREATE INDEX IF NOT EXISTS idx_context_pool_source_visibility
ON jarvis_shared_context_pool(source_agent, visibility, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_context_pool_domain
ON jarvis_shared_context_pool(domain, created_at DESC)
WHERE domain IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_context_pool_session
ON jarvis_shared_context_pool(session_id, created_at DESC)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_context_subscriptions_agent
ON jarvis_context_subscriptions(agent_id)
WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_context_boundaries_target
ON jarvis_context_privacy_boundaries(target_agent)
WHERE active = TRUE;

COMMENT ON TABLE jarvis_shared_context_pool IS 'Phase 22B-04: Cross-agent shared context pool';
COMMENT ON TABLE jarvis_context_subscriptions IS 'Phase 22B-05: Agent subscriptions to context updates';
COMMENT ON TABLE jarvis_context_privacy_boundaries IS 'Phase 22B-06: Privacy boundaries for context sharing';
COMMENT ON COLUMN jarvis_shared_context_pool.visibility IS 'global|domain|private|temporary';
