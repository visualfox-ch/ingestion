-- Migration 039: Memory relevance conflicts + graph edges

CREATE TABLE IF NOT EXISTS memory_fact_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id UUID NOT NULL,
    conflicting_fact_id UUID NOT NULL,
    conflict_type VARCHAR(50) NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_fact_conflicts_unique
    ON memory_fact_conflicts (fact_id, conflicting_fact_id, conflict_type);
CREATE INDEX IF NOT EXISTS idx_memory_fact_conflicts_fact
    ON memory_fact_conflicts (fact_id);
CREATE INDEX IF NOT EXISTS idx_memory_fact_conflicts_conflicting
    ON memory_fact_conflicts (conflicting_fact_id);
CREATE INDEX IF NOT EXISTS idx_memory_fact_conflicts_status
    ON memory_fact_conflicts (status);

CREATE TABLE IF NOT EXISTS memory_fact_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id UUID NOT NULL,
    related_fact_id UUID NOT NULL,
    relation_type VARCHAR(50) NOT NULL,
    weight DOUBLE PRECISION DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_fact_edges_unique
    ON memory_fact_edges (fact_id, related_fact_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_memory_fact_edges_fact
    ON memory_fact_edges (fact_id);
CREATE INDEX IF NOT EXISTS idx_memory_fact_edges_related
    ON memory_fact_edges (related_fact_id);
CREATE INDEX IF NOT EXISTS idx_memory_fact_edges_relation
    ON memory_fact_edges (relation_type);
