-- Migration: Jarvis Tool Autonomy Schema
-- Phase 19.6: Database-First Tool Management
-- Jarvis can now manage its own tools, prompts, and decision rules

-- ============================================================
-- 1. TOOL REGISTRY (replaces hardcoded TOOL_DEFINITIONS)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_tools (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT NOT NULL,

    -- JSON Schema for Claude's tool use
    input_schema JSONB NOT NULL DEFAULT '{"type": "object", "properties": {}}',

    -- Metadata
    category VARCHAR(50) DEFAULT 'general',
    subcategory VARCHAR(50),
    priority INTEGER DEFAULT 50,  -- Higher = shown first in prompt

    -- Control flags
    enabled BOOLEAN DEFAULT true,
    requires_approval BOOLEAN DEFAULT false,
    sandbox_only BOOLEAN DEFAULT false,

    -- Source tracking
    source VARCHAR(20) DEFAULT 'code',  -- code, dynamic, jarvis_created
    source_file VARCHAR(255),

    -- Usage optimization
    avg_latency_ms INTEGER,
    success_rate REAL,
    last_used_at TIMESTAMP,
    use_count INTEGER DEFAULT 0,

    -- Versioning
    version VARCHAR(20) DEFAULT '1.0',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(50) DEFAULT 'system',

    -- For A/B testing different descriptions
    alt_description TEXT,
    alt_enabled BOOLEAN DEFAULT false
);

CREATE INDEX idx_jarvis_tools_category ON jarvis_tools(category);
CREATE INDEX idx_jarvis_tools_enabled ON jarvis_tools(enabled);
CREATE INDEX idx_jarvis_tools_priority ON jarvis_tools(priority DESC);

-- ============================================================
-- 2. TOOL CATEGORIES (replaces hardcoded tool_categories)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_tool_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,

    -- Keywords that trigger this category
    keywords JSONB DEFAULT '[]',  -- ["keyword1", "keyword2"]

    -- Control
    enabled BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 50,

    -- Parent category for hierarchy
    parent_category VARCHAR(50),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 3. TOOL-CATEGORY MAPPINGS (many-to-many)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_tool_category_map (
    tool_name VARCHAR(100) REFERENCES jarvis_tools(name) ON DELETE CASCADE,
    category_name VARCHAR(50) REFERENCES jarvis_tool_categories(name) ON DELETE CASCADE,
    relevance_score REAL DEFAULT 1.0,  -- How relevant is this tool to this category
    PRIMARY KEY (tool_name, category_name)
);

-- ============================================================
-- 4. PROMPT FRAGMENTS (dynamic prompt building)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_prompt_fragments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    fragment_type VARCHAR(30) NOT NULL,  -- system, persona, instruction, guardrail, example

    content TEXT NOT NULL,

    -- When to include this fragment
    conditions JSONB DEFAULT '{}',  -- {"role": "coach", "user_mood": "stressed"}

    -- Control
    enabled BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 50,  -- Order in final prompt

    -- A/B Testing
    variant VARCHAR(20) DEFAULT 'default',

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(50) DEFAULT 'system'
);

CREATE INDEX idx_prompt_fragments_type ON jarvis_prompt_fragments(fragment_type);

-- ============================================================
-- 5. DECISION RULES (when to use which tools)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_decision_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,

    -- Rule definition
    condition_type VARCHAR(30) NOT NULL,  -- keyword, intent, context, pattern
    condition_value JSONB NOT NULL,  -- The actual condition

    -- Action when matched
    action_type VARCHAR(30) NOT NULL,  -- include_tools, exclude_tools, set_priority, require_approval
    action_value JSONB NOT NULL,  -- The action to take

    -- Control
    enabled BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 50,  -- Higher priority rules checked first

    -- Stats
    match_count INTEGER DEFAULT 0,
    last_matched_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(50) DEFAULT 'system'
);

CREATE INDEX idx_decision_rules_type ON jarvis_decision_rules(condition_type);
CREATE INDEX idx_decision_rules_enabled ON jarvis_decision_rules(enabled);

-- ============================================================
-- 6. RESPONSE STYLES (how Jarvis communicates)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_response_styles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,

    -- Style definition
    tone VARCHAR(30),  -- friendly, professional, casual, technical
    verbosity VARCHAR(20),  -- minimal, balanced, detailed
    emoji_level VARCHAR(20),  -- none, sparse, moderate, heavy
    language VARCHAR(10) DEFAULT 'de',

    -- Prompt additions for this style
    style_prompt TEXT,

    -- When to use
    conditions JSONB DEFAULT '{}',  -- {"user_preference": "casual", "time_of_day": "evening"}

    enabled BOOLEAN DEFAULT true,
    is_default BOOLEAN DEFAULT false,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 7. JARVIS SELF-MODIFICATIONS LOG (audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_self_modifications (
    id SERIAL PRIMARY KEY,

    -- What was modified
    target_table VARCHAR(50) NOT NULL,
    target_id INTEGER,
    target_name VARCHAR(100),

    -- The change
    modification_type VARCHAR(20) NOT NULL,  -- create, update, delete, enable, disable
    old_value JSONB,
    new_value JSONB,

    -- Why
    reason TEXT,
    confidence REAL,

    -- Approval tracking
    requires_approval BOOLEAN DEFAULT false,
    approved_at TIMESTAMP,
    approved_by VARCHAR(50),
    rejected_at TIMESTAMP,
    rejected_reason TEXT,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_self_mods_table ON jarvis_self_modifications(target_table);
CREATE INDEX idx_self_mods_approval ON jarvis_self_modifications(requires_approval, approved_at);

-- ============================================================
-- 8. TOOL EXECUTION LOG (for learning patterns)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_tool_executions (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR(100) NOT NULL,

    -- Execution context
    session_id VARCHAR(100),
    user_id INTEGER,
    query_hash VARCHAR(64),  -- Hash of the query that triggered this

    -- Result
    success BOOLEAN,
    latency_ms INTEGER,
    error_message TEXT,

    -- For pattern learning
    input_summary TEXT,  -- Condensed version of input
    output_summary TEXT,  -- Condensed version of output

    executed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tool_exec_name ON jarvis_tool_executions(tool_name);
CREATE INDEX idx_tool_exec_time ON jarvis_tool_executions(executed_at DESC);

-- Partition by month for performance (optional, commented out for compatibility)
-- CREATE INDEX idx_tool_exec_month ON jarvis_tool_executions(DATE_TRUNC('month', executed_at));

-- ============================================================
-- INITIAL DATA: Default Categories
-- ============================================================
INSERT INTO jarvis_tool_categories (name, display_name, description, keywords, priority) VALUES
('memory', 'Memory & Knowledge', 'Tools for storing and retrieving information',
 '["erinner", "remember", "speicher", "store", "recall", "wissen", "knowledge"]', 90),
('self_modification', 'Self-Improvement', 'Tools for Jarvis to modify itself',
 '["tool erstell", "create tool", "dynamic", "selbst", "improve", "optimier"]', 85),
('communication', 'Communication', 'Tools for messaging and notifications',
 '["telegram", "email", "nachricht", "message", "send", "notify"]', 80),
('calendar', 'Calendar & Scheduling', 'Tools for time management',
 '["kalender", "calendar", "termin", "event", "schedule", "meeting"]', 75),
('project', 'Project Management', 'Tools for tracking projects and tasks',
 '["projekt", "project", "task", "aufgabe", "status", "thread"]', 70),
('system', 'System & Health', 'Tools for system monitoring',
 '["health", "status", "system", "diagnos", "check", "pulse"]', 60),
('file', 'File Operations', 'Tools for reading and writing files',
 '["datei", "file", "read", "write", "lesen", "schreiben"]', 50),
('search', 'Search & Discovery', 'Tools for finding information',
 '["such", "search", "find", "query", "lookup"]', 70)
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- INITIAL DATA: Default Response Styles
-- ============================================================
INSERT INTO jarvis_response_styles (name, description, tone, verbosity, emoji_level, style_prompt, is_default) VALUES
('micha_default', 'Default style for Micha', 'friendly', 'balanced', 'sparse',
 'Antworte direkt und praktisch. Nutze Bullets. Keine langen Einleitungen.', true),
('technical', 'Technical deep-dive mode', 'professional', 'detailed', 'none',
 'Fokussiere auf technische Details. Code-Beispiele wenn hilfreich.', false),
('quick', 'Quick response mode', 'casual', 'minimal', 'none',
 'Maximal 2-3 Sätze. Nur das Wesentliche.', false),
('coaching', 'ADHD coaching mode', 'supportive', 'balanced', 'sparse',
 'Strukturiert mit klaren Next Steps. Maximal 3 Punkte. Vermeide Overwhelm.', false)
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- COMMENTS for documentation
-- ============================================================
COMMENT ON TABLE jarvis_tools IS 'Central registry of all tools Jarvis can use. Replaces hardcoded TOOL_DEFINITIONS.';
COMMENT ON TABLE jarvis_tool_categories IS 'Categories for organizing tools. Jarvis can create/modify these.';
COMMENT ON TABLE jarvis_prompt_fragments IS 'Dynamic prompt pieces. Jarvis can adjust its own personality.';
COMMENT ON TABLE jarvis_decision_rules IS 'Rules for when to use which tools. Jarvis learns and optimizes these.';
COMMENT ON TABLE jarvis_response_styles IS 'Communication styles Jarvis can switch between.';
COMMENT ON TABLE jarvis_self_modifications IS 'Audit log of all self-modifications for transparency.';
