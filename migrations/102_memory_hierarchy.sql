-- Phase B1: Memory Hierarchy (MemGPT-Style)
-- Based on Packer et al. (2023) "MemGPT: Towards LLMs as Operating Systems"
-- Tiered memory system with automatic promotion/demotion
-- Date: 2026-03-15

-- Memory tiers: working → recall → longterm → archive
CREATE TABLE IF NOT EXISTS memory_tiers (
    id SERIAL PRIMARY KEY,
    tier_name VARCHAR(50) NOT NULL UNIQUE,
    tier_level INTEGER NOT NULL,  -- 0=working, 1=recall, 2=longterm, 3=archive
    max_items INTEGER,            -- NULL = unlimited
    max_age_hours INTEGER,        -- Auto-demote after this time
    description TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Memory items: unified storage across tiers
CREATE TABLE IF NOT EXISTS memory_items (
    id SERIAL PRIMARY KEY,
    memory_key TEXT NOT NULL,     -- Unique identifier
    tier_id INTEGER REFERENCES memory_tiers(id),

    -- Content
    content TEXT NOT NULL,
    content_type VARCHAR(50) DEFAULT 'text',  -- text, summary, fact, episode
    summary TEXT,                 -- Compressed version for recall buffer

    -- Metadata
    source VARCHAR(100),          -- session, tool, user, system
    domain VARCHAR(100),
    tags JSONB DEFAULT '[]',

    -- Scoring (Generative Agents style)
    importance FLOAT DEFAULT 0.5,      -- 0-1, how important
    recency_score FLOAT DEFAULT 1.0,   -- Decays over time
    access_count INTEGER DEFAULT 0,
    last_accessed TIMESTAMPTZ DEFAULT NOW(),

    -- Relationships
    related_memories JSONB DEFAULT '[]',  -- [{memory_id, relationship, strength}]

    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    promoted_at TIMESTAMPTZ,
    demoted_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,

    -- Embedding reference
    embedding_id TEXT,            -- Reference to Qdrant point

    UNIQUE(memory_key)
);

-- Memory access log: for recency calculation
CREATE TABLE IF NOT EXISTS memory_access_log (
    id SERIAL PRIMARY KEY,
    memory_id INTEGER REFERENCES memory_items(id) ON DELETE CASCADE,
    access_type VARCHAR(50) NOT NULL,  -- read, write, search_hit, reference
    context TEXT,                       -- Why was it accessed
    session_id TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Memory summaries: compressed representations for recall buffer
CREATE TABLE IF NOT EXISTS memory_summaries (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(50) NOT NULL,   -- session, topic, timeframe, entity
    source_id TEXT,                     -- e.g., session_id or topic name

    -- Summary content
    summary TEXT NOT NULL,
    key_facts JSONB DEFAULT '[]',       -- Extracted key facts
    entities_mentioned JSONB DEFAULT '[]',

    -- Temporal scope
    time_start TIMESTAMPTZ,
    time_end TIMESTAMPTZ,

    -- Stats
    source_item_count INTEGER DEFAULT 0,
    compression_ratio FLOAT,            -- original_tokens / summary_tokens

    -- Lifecycle
    is_active BOOLEAN DEFAULT TRUE,
    last_refreshed TIMESTAMPTZ DEFAULT NOW(),
    refresh_count INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Memory contradictions: track conflicting memories
CREATE TABLE IF NOT EXISTS memory_contradictions (
    id SERIAL PRIMARY KEY,
    memory_id_a INTEGER REFERENCES memory_items(id) ON DELETE CASCADE,
    memory_id_b INTEGER REFERENCES memory_items(id) ON DELETE CASCADE,

    -- Contradiction details
    contradiction_type VARCHAR(50),  -- factual, temporal, logical
    description TEXT,
    severity FLOAT DEFAULT 0.5,      -- 0-1

    -- Resolution
    resolution_status VARCHAR(50) DEFAULT 'pending',  -- pending, resolved, dismissed
    resolution_method TEXT,          -- newer_wins, evidence, manual
    resolved_winner_id INTEGER,      -- Which memory was correct
    resolution_notes TEXT,

    detected_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- Working context snapshots: for quick restoration
CREATE TABLE IF NOT EXISTS working_context_snapshots (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,

    -- Context state
    active_memories JSONB DEFAULT '[]',   -- memory_ids in working context
    active_topics JSONB DEFAULT '[]',
    active_entities JSONB DEFAULT '[]',

    -- Stats
    total_tokens INTEGER,
    memory_count INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_memory_items_tier ON memory_items(tier_id);
CREATE INDEX IF NOT EXISTS idx_memory_items_key ON memory_items(memory_key);
CREATE INDEX IF NOT EXISTS idx_memory_items_domain ON memory_items(domain);
CREATE INDEX IF NOT EXISTS idx_memory_items_importance ON memory_items(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_items_recency ON memory_items(recency_score DESC);
CREATE INDEX IF NOT EXISTS idx_memory_items_accessed ON memory_items(last_accessed DESC);
CREATE INDEX IF NOT EXISTS idx_memory_access_memory ON memory_access_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_summaries_source ON memory_summaries(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memory_contradictions_status ON memory_contradictions(resolution_status);
CREATE INDEX IF NOT EXISTS idx_working_context_session ON working_context_snapshots(session_id);

-- Default memory tiers
INSERT INTO memory_tiers (tier_name, tier_level, max_items, max_age_hours, description) VALUES
('working', 0, 20, 2, 'Active working memory - currently relevant items'),
('recall', 1, 100, 168, 'Recall buffer - summarized, quick access (1 week)'),
('longterm', 2, NULL, 2160, 'Long-term storage - full content (90 days)'),
('archive', 3, NULL, NULL, 'Archive - compressed, permanent storage')
ON CONFLICT (tier_name) DO NOTHING;

-- Comments
COMMENT ON TABLE memory_tiers IS 'Phase B1: Memory tier definitions (MemGPT-style)';
COMMENT ON TABLE memory_items IS 'Phase B1: Unified memory storage across tiers';
COMMENT ON TABLE memory_access_log IS 'Phase B1: Memory access tracking for recency scoring';
COMMENT ON TABLE memory_summaries IS 'Phase B1: Compressed summaries for recall buffer';
COMMENT ON TABLE memory_contradictions IS 'Phase B1/B3: Memory contradiction tracking';
COMMENT ON TABLE working_context_snapshots IS 'Phase B1: Working context state snapshots';
