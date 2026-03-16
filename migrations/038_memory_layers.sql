-- Migration 038: Memory layers (L1/L2/L3)

CREATE TABLE IF NOT EXISTS memory_facts_layered (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    layer VARCHAR(5) NOT NULL CHECK (layer IN ('L1', 'L2', 'L3')),
    key VARCHAR(500) NOT NULL,
    value JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_expires_at TIMESTAMPTZ,

    layer_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    access_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,

    promoted_from_layer VARCHAR(5),
    promoted_at TIMESTAMPTZ,
    demotion_candidate BOOLEAN DEFAULT FALSE,

    user_id VARCHAR(100),
    session_id VARCHAR(100),
    namespace VARCHAR(100) DEFAULT 'private',

    search_vector tsvector,
    embedding_vector DOUBLE PRECISION[]
);

CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_layer
    ON memory_facts_layered(layer);
CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_ttl
    ON memory_facts_layered(ttl_expires_at)
    WHERE ttl_expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_user_layer
    ON memory_facts_layered(user_id, layer);
CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_namespace
    ON memory_facts_layered(namespace);
CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_accessed
    ON memory_facts_layered(accessed_at);
CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_confidence
    ON memory_facts_layered(confidence);
CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_search
    ON memory_facts_layered USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS memory_layer_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id UUID REFERENCES memory_facts_layered(id) ON DELETE CASCADE,
    from_layer VARCHAR(5),
    to_layer VARCHAR(5),
    transition_reason TEXT,
    confidence_before DOUBLE PRECISION,
    confidence_after DOUBLE PRECISION,
    transition_metadata JSONB,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_layer_transitions_fact
    ON memory_layer_transitions(fact_id);
CREATE INDEX IF NOT EXISTS idx_memory_layer_transitions_time
    ON memory_layer_transitions(transitioned_at DESC);
