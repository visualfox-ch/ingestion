-- Phase B3: Contradiction Resolution
-- Detect and resolve conflicting memories
-- Based on CLIN (Conceptual Lifelong Interaction) pattern
-- Date: 2026-03-15

-- Contradiction types: categories of conflicts
CREATE TABLE IF NOT EXISTS contradiction_types (
    id SERIAL PRIMARY KEY,
    type_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    severity_default FLOAT DEFAULT 0.5,  -- 0-1
    resolution_strategy VARCHAR(50),      -- newer_wins, evidence_based, manual, merge

    examples JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Contradiction detections: found conflicts
CREATE TABLE IF NOT EXISTS contradiction_detections (
    id SERIAL PRIMARY KEY,

    -- The conflicting memories
    memory_id_a INTEGER,
    memory_id_b INTEGER,
    memory_key_a TEXT,
    memory_key_b TEXT,

    -- Contradiction details
    contradiction_type_id INTEGER REFERENCES contradiction_types(id),
    description TEXT NOT NULL,
    severity FLOAT DEFAULT 0.5,          -- 0-1
    confidence FLOAT DEFAULT 0.5,        -- How confident we are this is a contradiction

    -- Evidence
    evidence_for_a JSONB DEFAULT '[]',   -- [{source, weight, description}]
    evidence_for_b JSONB DEFAULT '[]',

    -- Context
    domain VARCHAR(100),
    detected_by VARCHAR(50),             -- automatic, user_flagged, review

    -- Status
    status VARCHAR(50) DEFAULT 'pending',  -- pending, investigating, resolved, dismissed
    priority VARCHAR(20) DEFAULT 'medium', -- low, medium, high, critical

    detected_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Contradiction resolutions: how conflicts were resolved
CREATE TABLE IF NOT EXISTS contradiction_resolutions (
    id SERIAL PRIMARY KEY,
    detection_id INTEGER REFERENCES contradiction_detections(id) ON DELETE CASCADE,

    -- Resolution
    resolution_method VARCHAR(50) NOT NULL,  -- newer_wins, evidence_weight, manual, merge, both_valid
    winner_memory_id INTEGER,
    winner_memory_key TEXT,

    -- Details
    resolution_reasoning TEXT,
    merged_content TEXT,                     -- If resolution was merge

    -- Outcome
    loser_action VARCHAR(50),                -- archived, deleted, updated, kept
    confidence_adjustment FLOAT,             -- How much to adjust loser confidence

    -- Metadata
    resolved_by VARCHAR(50),                 -- system, user
    resolved_at TIMESTAMPTZ DEFAULT NOW(),

    -- Verification
    was_verified BOOLEAN,
    verification_outcome TEXT
);

-- Evidence sources: track where evidence comes from
CREATE TABLE IF NOT EXISTS evidence_sources (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL UNIQUE,
    source_type VARCHAR(50),                  -- user, system, external, derived
    reliability FLOAT DEFAULT 0.7,            -- 0-1, how reliable is this source
    description TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Fact versions: track how facts change over time
CREATE TABLE IF NOT EXISTS fact_versions (
    id SERIAL PRIMARY KEY,
    fact_key TEXT NOT NULL,                   -- Unique identifier for the fact
    version_number INTEGER DEFAULT 1,

    -- Content
    content TEXT NOT NULL,
    previous_content TEXT,

    -- Metadata
    source TEXT,
    confidence FLOAT DEFAULT 0.5,
    valid_from TIMESTAMPTZ DEFAULT NOW(),
    valid_until TIMESTAMPTZ,                  -- NULL = still valid

    -- Change tracking
    change_reason TEXT,
    changed_by VARCHAR(50),

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(fact_key, version_number)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_contradiction_detections_status ON contradiction_detections(status);
CREATE INDEX IF NOT EXISTS idx_contradiction_detections_type ON contradiction_detections(contradiction_type_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_detections_priority ON contradiction_detections(priority);
CREATE INDEX IF NOT EXISTS idx_contradiction_detections_memory_a ON contradiction_detections(memory_id_a);
CREATE INDEX IF NOT EXISTS idx_contradiction_detections_memory_b ON contradiction_detections(memory_id_b);
CREATE INDEX IF NOT EXISTS idx_contradiction_resolutions_detection ON contradiction_resolutions(detection_id);
CREATE INDEX IF NOT EXISTS idx_fact_versions_key ON fact_versions(fact_key);
CREATE INDEX IF NOT EXISTS idx_fact_versions_valid ON fact_versions(valid_until) WHERE valid_until IS NULL;

-- Default contradiction types
INSERT INTO contradiction_types (type_name, description, severity_default, resolution_strategy) VALUES
('factual', 'Two memories state conflicting facts', 0.7, 'evidence_based'),
('temporal', 'Memories conflict about when something happened', 0.5, 'newer_wins'),
('logical', 'Memories are logically inconsistent', 0.6, 'evidence_based'),
('preference', 'Memories indicate different user preferences', 0.4, 'newer_wins'),
('state', 'Memories indicate different current states', 0.5, 'newer_wins'),
('attribution', 'Different sources attributed to same information', 0.3, 'evidence_based'),
('quantity', 'Different numbers/quantities stated', 0.6, 'evidence_based'),
('identity', 'Conflicting information about who/what something is', 0.7, 'manual')
ON CONFLICT (type_name) DO NOTHING;

-- Default evidence sources
INSERT INTO evidence_sources (source_name, source_type, reliability, description) VALUES
('user_statement', 'user', 0.9, 'Direct statement from user'),
('user_correction', 'user', 0.95, 'User explicitly corrected a fact'),
('system_observation', 'system', 0.8, 'System observed this directly'),
('external_api', 'external', 0.7, 'Retrieved from external API'),
('derived_inference', 'derived', 0.5, 'Inferred from other facts'),
('historical_pattern', 'derived', 0.6, 'Based on historical patterns')
ON CONFLICT (source_name) DO NOTHING;

-- Comments
COMMENT ON TABLE contradiction_types IS 'Phase B3: Types of contradictions between memories';
COMMENT ON TABLE contradiction_detections IS 'Phase B3: Detected contradictions awaiting resolution';
COMMENT ON TABLE contradiction_resolutions IS 'Phase B3: How contradictions were resolved';
COMMENT ON TABLE evidence_sources IS 'Phase B3: Sources of evidence for resolution';
COMMENT ON TABLE fact_versions IS 'Phase B3: Version history of facts';
