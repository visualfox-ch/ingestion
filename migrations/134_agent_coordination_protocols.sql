-- Migration 134: Agent Coordination Protocols (Phase 22B-07/08/09)

CREATE TABLE IF NOT EXISTS jarvis_agent_negotiations (
    id SERIAL PRIMARY KEY,
    negotiation_id VARCHAR(50) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    original_query TEXT,
    initiator_agent VARCHAR(50) NOT NULL,
    strategy VARCHAR(30) NOT NULL,
    state VARCHAR(30) NOT NULL DEFAULT 'proposed',
    candidate_agents JSONB DEFAULT '[]'::jsonb,
    context JSONB DEFAULT '{}'::jsonb,
    chosen_agent VARCHAR(50),
    arbitration_agent VARCHAR(50),
    conflict_reason TEXT,
    consensus_summary JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jarvis_agent_negotiation_positions (
    id SERIAL PRIMARY KEY,
    negotiation_id VARCHAR(50) NOT NULL,
    agent_name VARCHAR(50) NOT NULL,
    position_type VARCHAR(20) NOT NULL,
    capability_score REAL,
    bid_score REAL,
    vote_value VARCHAR(20),
    rationale TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(negotiation_id, agent_name, position_type)
);

CREATE TABLE IF NOT EXISTS jarvis_agent_coordination_events (
    id SERIAL PRIMARY KEY,
    negotiation_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    actor_agent VARCHAR(50),
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_negotiations_state_strategy
ON jarvis_agent_negotiations(state, strategy, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_negotiation_positions_lookup
ON jarvis_agent_negotiation_positions(negotiation_id, position_type, created_at);

CREATE INDEX IF NOT EXISTS idx_coordination_events_lookup
ON jarvis_agent_coordination_events(negotiation_id, created_at);

COMMENT ON TABLE jarvis_agent_negotiations IS 'Phase 22B-07/08/09: Negotiation, conflict resolution, and consensus sessions';
COMMENT ON TABLE jarvis_agent_negotiation_positions IS 'Claims, bids, and votes for agent coordination';
COMMENT ON TABLE jarvis_agent_coordination_events IS 'Audit/event trail for agent coordination decisions';