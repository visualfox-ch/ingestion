-- Phase A3: Causal Knowledge Graph
-- Based on Pearl's Causal Inference (2009)
-- Enables understanding of cause-effect relationships, not just correlations
-- Date: 2026-03-15

-- Causal nodes: entities in the causal graph
CREATE TABLE IF NOT EXISTS causal_nodes (
    id SERIAL PRIMARY KEY,
    node_name TEXT NOT NULL,
    node_type VARCHAR(50) NOT NULL,  -- event, state, action, entity, concept
    domain VARCHAR(100),
    description TEXT,

    -- Node properties
    is_observable BOOLEAN DEFAULT TRUE,   -- Can we observe this directly?
    is_manipulable BOOLEAN DEFAULT FALSE, -- Can we intervene on this?
    typical_values JSONB DEFAULT '[]',    -- Typical values/states

    -- Tracking
    occurrence_count INTEGER DEFAULT 0,
    last_observed TIMESTAMPTZ,
    confidence FLOAT DEFAULT 0.5,

    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(node_name, domain)
);

-- Causal edges: cause-effect relationships
CREATE TABLE IF NOT EXISTS causal_edges (
    id SERIAL PRIMARY KEY,
    cause_node_id INTEGER REFERENCES causal_nodes(id) ON DELETE CASCADE,
    effect_node_id INTEGER REFERENCES causal_nodes(id) ON DELETE CASCADE,

    -- Relationship properties
    relationship_type VARCHAR(50) NOT NULL,  -- causes, enables, prevents, influences, requires
    strength FLOAT DEFAULT 0.5,              -- 0-1, how strong is the causal link
    confidence FLOAT DEFAULT 0.5,            -- 0-1, how confident are we

    -- Causal details
    mechanism TEXT,                          -- How does cause lead to effect?
    conditions JSONB DEFAULT '[]',           -- Under what conditions?
    time_lag_minutes INTEGER,                -- Typical delay between cause and effect
    is_reversible BOOLEAN DEFAULT TRUE,

    -- Evidence tracking
    observation_count INTEGER DEFAULT 1,
    last_observed TIMESTAMPTZ DEFAULT NOW(),
    supporting_evidence JSONB DEFAULT '[]',  -- [{source, observation, timestamp}]
    contradicting_evidence JSONB DEFAULT '[]',

    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(cause_node_id, effect_node_id, relationship_type)
);

-- Causal observations: recorded cause-effect instances
CREATE TABLE IF NOT EXISTS causal_observations (
    id SERIAL PRIMARY KEY,
    edge_id INTEGER REFERENCES causal_edges(id) ON DELETE CASCADE,

    -- Observation details
    cause_value TEXT,
    effect_value TEXT,
    context JSONB DEFAULT '{}',

    -- Timing
    cause_timestamp TIMESTAMPTZ,
    effect_timestamp TIMESTAMPTZ,
    lag_minutes INTEGER,

    -- Verification
    was_predicted BOOLEAN DEFAULT FALSE,
    prediction_correct BOOLEAN,

    session_id TEXT,
    source TEXT,  -- user_feedback, system_observation, inference

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Causal queries: track causal reasoning requests
CREATE TABLE IF NOT EXISTS causal_queries (
    id SERIAL PRIMARY KEY,
    query_type VARCHAR(50) NOT NULL,  -- why, what_if, how_to, predict
    query_text TEXT NOT NULL,

    -- Query components
    target_node_id INTEGER REFERENCES causal_nodes(id),
    intervention_node_id INTEGER,  -- For what-if queries
    intervention_value TEXT,

    -- Result
    reasoning_chain JSONB DEFAULT '[]',  -- [{step, node, relationship, confidence}]
    answer TEXT,
    confidence FLOAT,

    -- Verification
    was_verified BOOLEAN,
    verification_result TEXT,

    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Causal interventions: do(X) operations
CREATE TABLE IF NOT EXISTS causal_interventions (
    id SERIAL PRIMARY KEY,
    intervention_type VARCHAR(50) NOT NULL,  -- set, increase, decrease, toggle
    target_node_id INTEGER REFERENCES causal_nodes(id),

    -- Intervention details
    target_value TEXT,
    original_value TEXT,

    -- Predictions
    predicted_effects JSONB DEFAULT '[]',  -- [{node_id, predicted_value, confidence}]
    actual_effects JSONB DEFAULT '[]',     -- Filled in after observation

    -- Outcome
    intervention_timestamp TIMESTAMPTZ DEFAULT NOW(),
    observation_timestamp TIMESTAMPTZ,
    prediction_accuracy FLOAT,

    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_causal_nodes_name ON causal_nodes(node_name);
CREATE INDEX IF NOT EXISTS idx_causal_nodes_type ON causal_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_causal_nodes_domain ON causal_nodes(domain);
CREATE INDEX IF NOT EXISTS idx_causal_edges_cause ON causal_edges(cause_node_id);
CREATE INDEX IF NOT EXISTS idx_causal_edges_effect ON causal_edges(effect_node_id);
CREATE INDEX IF NOT EXISTS idx_causal_edges_type ON causal_edges(relationship_type);
CREATE INDEX IF NOT EXISTS idx_causal_observations_edge ON causal_observations(edge_id);
CREATE INDEX IF NOT EXISTS idx_causal_queries_type ON causal_queries(query_type);
CREATE INDEX IF NOT EXISTS idx_causal_interventions_node ON causal_interventions(target_node_id);

-- Default causal relationship types
CREATE TABLE IF NOT EXISTS causal_relationship_types (
    id SERIAL PRIMARY KEY,
    type_name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_deterministic BOOLEAN DEFAULT FALSE,
    typical_strength FLOAT DEFAULT 0.5,
    examples JSONB DEFAULT '[]'
);

INSERT INTO causal_relationship_types (type_name, description, is_deterministic, typical_strength) VALUES
('causes', 'Direct causal relationship - X causes Y', FALSE, 0.7),
('enables', 'X makes Y possible but does not guarantee it', FALSE, 0.5),
('prevents', 'X prevents or reduces likelihood of Y', FALSE, 0.6),
('influences', 'X has some effect on Y (direction/strength varies)', FALSE, 0.4),
('requires', 'Y requires X as a precondition', TRUE, 0.9),
('triggers', 'X initiates Y (often with time delay)', FALSE, 0.7),
('inhibits', 'X reduces the strength/likelihood of Y', FALSE, 0.5),
('correlates', 'X and Y co-occur (may have common cause)', FALSE, 0.3),
('precedes', 'X typically happens before Y (temporal)', FALSE, 0.4),
('follows', 'X typically happens after Y (temporal)', FALSE, 0.4)
ON CONFLICT (type_name) DO NOTHING;

-- Comments
COMMENT ON TABLE causal_nodes IS 'Phase A3: Entities in the causal knowledge graph';
COMMENT ON TABLE causal_edges IS 'Phase A3: Cause-effect relationships between nodes';
COMMENT ON TABLE causal_observations IS 'Phase A3: Observed instances of causal relationships';
COMMENT ON TABLE causal_queries IS 'Phase A3: Causal reasoning queries and their results';
COMMENT ON TABLE causal_interventions IS 'Phase A3: do(X) operations and their outcomes';
