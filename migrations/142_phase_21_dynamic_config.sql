-- Phase 21: Dynamic Configuration System
-- Moves hardcoded configs to database for runtime modification
-- Created: 2026-03-11

-- ============================================
-- 1. JARVIS_ROLES - Dynamic Role Definitions
-- ============================================
CREATE TABLE IF NOT EXISTS jarvis_roles (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    system_prompt_addon TEXT,
    greeting TEXT,
    keywords TEXT,  -- JSON array of trigger keywords
    default_namespace TEXT DEFAULT 'work_projektil',
    enabled INTEGER DEFAULT 1,
    usage_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    avg_response_time_ms INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_jarvis_roles_enabled ON jarvis_roles(enabled);
CREATE INDEX IF NOT EXISTS idx_jarvis_roles_usage ON jarvis_roles(usage_count DESC);

-- ============================================
-- 2. QUERY_PATTERNS - Learnable Query Classification
-- ============================================
CREATE TABLE IF NOT EXISTS query_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    pattern_type TEXT NOT NULL,  -- 'simple', 'standard', 'complex'
    category TEXT,  -- 'greeting', 'status', 'search', 'analysis', etc.
    is_regex INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    hit_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_hit TEXT,
    source TEXT DEFAULT 'hardcoded',  -- 'hardcoded', 'learned', 'user_defined'
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_query_patterns_type ON query_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_query_patterns_enabled ON query_patterns(enabled);
CREATE UNIQUE INDEX IF NOT EXISTS idx_query_patterns_unique ON query_patterns(pattern, pattern_type);

-- ============================================
-- 3. SKILL_REGISTRY - Skill Management
-- ============================================
CREATE TABLE IF NOT EXISTS skill_registry (
    name TEXT PRIMARY KEY,
    category TEXT,
    description TEXT,
    triggers TEXT,  -- JSON array of trigger phrases
    not_triggers TEXT,  -- JSON array of exclusion phrases
    required_tools TEXT,  -- JSON array of tool names
    time_triggers TEXT,  -- JSON for scheduled triggers
    auto_trigger_condition TEXT,  -- Condition for auto-activation
    skill_level INTEGER DEFAULT 1,
    enabled INTEGER DEFAULT 1,
    usage_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    avg_duration_ms INTEGER DEFAULT 0,
    last_used TEXT,
    skill_path TEXT,  -- Path to SKILL.md file
    version TEXT DEFAULT '1.0',
    author TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_registry_enabled ON skill_registry(enabled);
CREATE INDEX IF NOT EXISTS idx_skill_registry_category ON skill_registry(category);

-- Skill execution audit log
CREATE TABLE IF NOT EXISTS skill_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    session_id TEXT,
    user_id TEXT,
    trigger_phrase TEXT,
    input_summary TEXT,
    output_summary TEXT,
    tools_used TEXT,  -- JSON array
    duration_ms INTEGER,
    success INTEGER,
    error_message TEXT,
    executed_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (skill_name) REFERENCES skill_registry(name)
);

CREATE INDEX IF NOT EXISTS idx_skill_executions_skill ON skill_executions(skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_executions_date ON skill_executions(executed_at);

-- ============================================
-- 4. SYSTEM_PROMPTS - Versioned Prompts
-- ============================================
CREATE TABLE IF NOT EXISTS system_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,  -- 'main', 'compact', 'minimal', 'custom_*'
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    description TEXT,
    token_estimate INTEGER,
    active INTEGER DEFAULT 0,
    performance_score REAL,  -- For A/B testing
    usage_count INTEGER DEFAULT 0,
    avg_quality_score REAL,
    created_at TEXT DEFAULT (datetime('now')),
    created_by TEXT DEFAULT 'system',
    UNIQUE(name, version)
);

CREATE INDEX IF NOT EXISTS idx_system_prompts_active ON system_prompts(name, active);
CREATE INDEX IF NOT EXISTS idx_system_prompts_version ON system_prompts(name, version DESC);

-- Prompt performance tracking for A/B testing
CREATE TABLE IF NOT EXISTS prompt_ab_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    prompt_a_id INTEGER NOT NULL,
    prompt_b_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT DEFAULT 'running',  -- 'running', 'completed', 'cancelled'
    winner_id INTEGER,
    metrics TEXT,  -- JSON with comparison metrics
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (prompt_a_id) REFERENCES system_prompts(id),
    FOREIGN KEY (prompt_b_id) REFERENCES system_prompts(id)
);

-- ============================================
-- 5. ENTITIES - Person/Project Intelligence
-- ============================================
-- Note: This table may already exist in jarvis_memory.db
-- We ensure it has the right schema
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,  -- 'person', 'project', 'company', 'concept'
    aliases TEXT,  -- JSON array of alternative names
    metadata TEXT,  -- JSON with type-specific data
    namespace TEXT DEFAULT 'shared',
    importance TEXT DEFAULT 'medium',  -- 'low', 'medium', 'high', 'critical'
    last_mentioned TEXT,
    mention_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_unique ON entities(name, entity_type, namespace);

-- Entity relationships
CREATE TABLE IF NOT EXISTS entity_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    related_entity_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,  -- 'works_with', 'manages', 'part_of', 'related_to'
    strength REAL DEFAULT 0.5,
    metadata TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    FOREIGN KEY (related_entity_id) REFERENCES entities(id)
);

CREATE INDEX IF NOT EXISTS idx_entity_relations_entity ON entity_relations(entity_id);

-- ============================================
-- 6. COST_TRACKING - API Cost Recording
-- ============================================
-- Ensure cost_entries table exists with proper schema
CREATE TABLE IF NOT EXISTS cost_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    model TEXT NOT NULL,
    provider TEXT NOT NULL,  -- 'anthropic', 'openai', 'ollama'
    feature TEXT NOT NULL,  -- 'agent', 'search', 'embedding', 'tts', 'stt'
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    session_id TEXT,
    user_id TEXT,
    namespace TEXT,
    latency_ms INTEGER,
    success INTEGER DEFAULT 1,
    metadata TEXT  -- JSON for additional context
);

CREATE INDEX IF NOT EXISTS idx_cost_entries_timestamp ON cost_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_entries_model ON cost_entries(model);
CREATE INDEX IF NOT EXISTS idx_cost_entries_feature ON cost_entries(feature);
CREATE INDEX IF NOT EXISTS idx_cost_entries_session ON cost_entries(session_id);

-- Daily aggregates for faster reporting
CREATE TABLE IF NOT EXISTS cost_daily_aggregates (
    date TEXT NOT NULL,
    model TEXT NOT NULL,
    feature TEXT NOT NULL,
    total_requests INTEGER DEFAULT 0,
    total_tokens_in INTEGER DEFAULT 0,
    total_tokens_out INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    avg_latency_ms INTEGER,
    success_rate REAL,
    PRIMARY KEY (date, model, feature)
);

-- Model pricing table (updateable without code changes)
CREATE TABLE IF NOT EXISTS model_costs (
    model TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    input_cost_per_1k REAL NOT NULL,
    output_cost_per_1k REAL NOT NULL,
    context_window INTEGER,
    max_output_tokens INTEGER,
    enabled INTEGER DEFAULT 1,
    notes TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- INITIAL DATA MIGRATIONS
-- ============================================

-- Insert default model costs
INSERT OR IGNORE INTO model_costs (model, provider, input_cost_per_1k, output_cost_per_1k, context_window, max_output_tokens) VALUES
    ('claude-3-5-haiku-20241022', 'anthropic', 0.001, 0.005, 200000, 8192),
    ('claude-sonnet-4-20250514', 'anthropic', 0.003, 0.015, 200000, 8192),
    ('claude-3-5-sonnet-20241022', 'anthropic', 0.003, 0.015, 200000, 8192),
    ('claude-3-opus-20240229', 'anthropic', 0.015, 0.075, 200000, 4096),
    ('gpt-4o', 'openai', 0.005, 0.015, 128000, 4096),
    ('gpt-4o-mini', 'openai', 0.00015, 0.0006, 128000, 16384),
    ('gpt-4-turbo', 'openai', 0.01, 0.03, 128000, 4096);
