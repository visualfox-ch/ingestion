-- Migration 036: Memory hygiene metadata + operations log

ALTER TABLE learned_facts
    ADD COLUMN IF NOT EXISTS memory_tier VARCHAR(20),
    ADD COLUMN IF NOT EXISTS decay_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS access_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_learned_facts_decay
    ON learned_facts (decay_date)
    WHERE decay_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_learned_facts_tier
    ON learned_facts (memory_tier);
CREATE INDEX IF NOT EXISTS idx_learned_facts_access
    ON learned_facts (access_count DESC);

CREATE TABLE IF NOT EXISTS hygiene_operations (
    id SERIAL PRIMARY KEY,
    operation_type VARCHAR(50) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    facts_processed INTEGER DEFAULT 0,
    facts_removed INTEGER DEFAULT 0,
    facts_consolidated INTEGER DEFAULT 0,
    storage_freed_bytes BIGINT DEFAULT 0,
    quality_score DOUBLE PRECISION,
    error_message TEXT,
    status VARCHAR(20) DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS hygiene_tombstones (
    original_fact_id TEXT NOT NULL,
    operation_id INTEGER REFERENCES hygiene_operations(id),
    original_data JSONB NOT NULL,
    tombstone_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '30 days'
);

CREATE TABLE IF NOT EXISTS hygiene_baselines (
    id SERIAL PRIMARY KEY,
    namespace TEXT,
    window_days INTEGER DEFAULT 30,
    metrics JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hygiene_baselines_namespace
    ON hygiene_baselines(namespace, created_at DESC);
