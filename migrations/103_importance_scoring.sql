-- Phase B2: Importance Scoring (Generative Agents Style)
-- Based on Park et al. (2023) "Generative Agents: Interactive Simulacra"
-- Relevance = recency + importance + similarity
-- Date: 2026-03-15

-- Importance factors: what makes something important
CREATE TABLE IF NOT EXISTS importance_factors (
    id SERIAL PRIMARY KEY,
    factor_name VARCHAR(100) NOT NULL UNIQUE,
    factor_type VARCHAR(50) NOT NULL,  -- content, context, entity, emotional

    -- Detection
    detection_pattern TEXT,           -- Regex or keyword pattern
    detection_method VARCHAR(50),     -- pattern, semantic, heuristic

    -- Scoring
    base_score FLOAT DEFAULT 0.5,     -- Default importance contribution
    weight FLOAT DEFAULT 1.0,         -- Weight when combining factors

    -- Examples
    examples JSONB DEFAULT '[]',
    description TEXT,

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Importance assessments: scored memories
CREATE TABLE IF NOT EXISTS importance_assessments (
    id SERIAL PRIMARY KEY,
    memory_id INTEGER,                -- Reference to memory_items
    memory_key TEXT,                  -- Alternative reference

    -- Component scores
    raw_importance FLOAT,             -- Initial importance estimate
    recency_score FLOAT,              -- Time-decay score
    access_frequency FLOAT,           -- How often accessed
    reference_count FLOAT,            -- How often referenced by others

    -- Factor breakdown
    factors_detected JSONB DEFAULT '[]',  -- [{factor_id, factor_name, contribution}]
    emotional_valence FLOAT,              -- -1 to 1 (negative to positive)
    personal_relevance FLOAT,             -- How relevant to user

    -- Final scores
    composite_score FLOAT,            -- Weighted combination
    normalized_score FLOAT,           -- 0-1 normalized

    -- Metadata
    scoring_version VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Retrieval requests: track what was retrieved and why
CREATE TABLE IF NOT EXISTS retrieval_requests (
    id SERIAL PRIMARY KEY,
    query_text TEXT,
    query_embedding_id TEXT,          -- Qdrant point ID for query

    -- Retrieval parameters
    recency_weight FLOAT DEFAULT 0.3,
    importance_weight FLOAT DEFAULT 0.4,
    similarity_weight FLOAT DEFAULT 0.3,

    -- Results
    results_count INTEGER,
    top_results JSONB DEFAULT '[]',   -- [{memory_id, score, rank}]

    -- Performance
    retrieval_time_ms INTEGER,

    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Recency decay configuration
CREATE TABLE IF NOT EXISTS recency_decay_config (
    id SERIAL PRIMARY KEY,
    config_name VARCHAR(100) NOT NULL UNIQUE,

    -- Decay parameters
    half_life_hours FLOAT DEFAULT 24,     -- Score halves every N hours
    min_score FLOAT DEFAULT 0.01,         -- Floor for recency
    boost_on_access FLOAT DEFAULT 1.0,    -- Reset to this on access

    -- Context-specific decay
    context_multipliers JSONB DEFAULT '{}',  -- {"work": 0.8, "personal": 1.2}

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Entity importance: track importance of entities (people, projects, etc.)
CREATE TABLE IF NOT EXISTS entity_importance (
    id SERIAL PRIMARY KEY,
    entity_name TEXT NOT NULL,
    entity_type VARCHAR(50),          -- person, project, concept, location

    -- Importance metrics
    mention_count INTEGER DEFAULT 0,
    interaction_count INTEGER DEFAULT 0,
    last_interaction TIMESTAMPTZ,

    -- Derived scores
    base_importance FLOAT DEFAULT 0.5,
    relationship_strength FLOAT,       -- For people
    current_relevance FLOAT,           -- Time-weighted

    -- Boost/decay
    manual_boost FLOAT DEFAULT 0,      -- User-specified importance adjustment

    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(entity_name, entity_type)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_importance_assessments_memory ON importance_assessments(memory_id);
CREATE INDEX IF NOT EXISTS idx_importance_assessments_key ON importance_assessments(memory_key);
CREATE INDEX IF NOT EXISTS idx_importance_assessments_score ON importance_assessments(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_retrieval_requests_session ON retrieval_requests(session_id);
CREATE INDEX IF NOT EXISTS idx_entity_importance_name ON entity_importance(entity_name);
CREATE INDEX IF NOT EXISTS idx_entity_importance_type ON entity_importance(entity_type);

-- Default importance factors
INSERT INTO importance_factors (factor_name, factor_type, detection_pattern, base_score, weight, description) VALUES
-- Content factors
('personal_reference', 'content', 'ich|mir|mein|my|me|mine', 0.7, 1.2, 'References to self'),
('user_reference', 'content', 'du|dir|dein|you|your', 0.6, 1.1, 'References to user'),
('action_item', 'content', 'todo|task|aufgabe|erledigen|must|should|soll', 0.8, 1.3, 'Action items and tasks'),
('decision', 'content', 'entschieden|decided|beschlossen|choice|wahl', 0.75, 1.2, 'Decisions made'),
('question', 'content', '\?|frage|question|warum|why|wie|how', 0.5, 1.0, 'Questions asked'),

-- Emotional factors
('positive_emotion', 'emotional', 'gut|great|super|toll|amazing|freude|happy|excited', 0.6, 1.0, 'Positive emotions'),
('negative_emotion', 'emotional', 'schlecht|bad|problem|fehler|error|frustrated|worried', 0.7, 1.1, 'Negative emotions (often important)'),
('urgency', 'emotional', 'urgent|dringend|asap|sofort|immediately|wichtig|critical', 0.9, 1.4, 'Urgency markers'),

-- Context factors
('meeting_context', 'context', 'meeting|besprechung|call|discussion|sync', 0.65, 1.1, 'Meeting-related'),
('project_context', 'context', 'projekt|project|milestone|deadline|release', 0.7, 1.2, 'Project-related'),
('learning_context', 'context', 'learned|gelernt|verstanden|understood|realized|erkannt', 0.75, 1.2, 'Learning moments'),

-- Entity factors
('person_mention', 'entity', NULL, 0.6, 1.1, 'Mentions of people (detected semantically)'),
('date_reference', 'entity', '\d{4}-\d{2}-\d{2}|morgen|tomorrow|gestern|yesterday|nächste woche', 0.5, 1.0, 'Date references')
ON CONFLICT (factor_name) DO NOTHING;

-- Default recency decay config
INSERT INTO recency_decay_config (config_name, half_life_hours, min_score, boost_on_access) VALUES
('default', 24, 0.01, 1.0),
('slow_decay', 168, 0.05, 1.0),   -- Weekly half-life
('fast_decay', 4, 0.01, 1.0)      -- 4-hour half-life for ephemeral
ON CONFLICT (config_name) DO NOTHING;

-- Comments
COMMENT ON TABLE importance_factors IS 'Phase B2: Factors that contribute to memory importance';
COMMENT ON TABLE importance_assessments IS 'Phase B2: Scored importance for each memory';
COMMENT ON TABLE retrieval_requests IS 'Phase B2: Track retrieval patterns and performance';
COMMENT ON TABLE recency_decay_config IS 'Phase B2: Recency decay parameters';
COMMENT ON TABLE entity_importance IS 'Phase B2: Importance tracking for entities';
