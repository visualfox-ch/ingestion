-- Migration: Dynamic Model Routing for Jarvis
-- Phase 21+: Fully learnable model selection
-- All patterns, indicators, and rules in database for Jarvis to optimize

-- ============================================================
-- 1. TASK CLASSIFICATION PATTERNS (lernbar)
-- ============================================================

CREATE TABLE IF NOT EXISTS jarvis_task_patterns (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    pattern_text TEXT NOT NULL,
    pattern_type VARCHAR(20) DEFAULT 'regex',  -- 'keyword', 'regex', 'phrase'
    language VARCHAR(10) DEFAULT 'both',       -- 'de', 'en', 'both'

    -- Learning metrics
    hit_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_hit TIMESTAMP,
    confidence DECIMAL(5,4) DEFAULT 0.7,

    -- Source tracking
    source VARCHAR(20) DEFAULT 'seed',         -- 'seed', 'learned', 'jarvis_override'
    created_by VARCHAR(50) DEFAULT 'system',
    notes TEXT,

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_patterns_type ON jarvis_task_patterns(task_type);
CREATE INDEX IF NOT EXISTS idx_task_patterns_active ON jarvis_task_patterns(is_active);

-- ============================================================
-- 2. COMPLEXITY INDICATORS (lernbar)
-- ============================================================

CREATE TABLE IF NOT EXISTS jarvis_complexity_patterns (
    id SERIAL PRIMARY KEY,
    indicator_type VARCHAR(10) NOT NULL,  -- 'high', 'low'
    pattern_text TEXT NOT NULL,
    pattern_type VARCHAR(20) DEFAULT 'regex',
    weight DECIMAL(3,2) DEFAULT 0.2,      -- How much to adjust complexity (±)

    -- Learning metrics
    hit_count INTEGER DEFAULT 0,
    effectiveness DECIMAL(5,4) DEFAULT 0.5,  -- How well it predicts actual complexity

    source VARCHAR(20) DEFAULT 'seed',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. MODEL LEARNING (aggregierte Performance-Daten)
-- ============================================================

CREATE TABLE IF NOT EXISTS jarvis_model_learning (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    model_id VARCHAR(100) NOT NULL,
    context_type VARCHAR(50) DEFAULT 'default',  -- 'morning', 'urgent', 'casual', etc.

    -- Aggregated metrics (updated by learning job)
    total_uses INTEGER DEFAULT 0,
    avg_latency_ms DECIMAL(10,2) DEFAULT 0,
    avg_quality_score DECIMAL(5,4) DEFAULT 0.5,
    total_cost_usd DECIMAL(10,6) DEFAULT 0,
    success_rate DECIMAL(5,4) DEFAULT 1.0,

    -- Computed efficiency: quality / (latency_normalized * cost_normalized)
    efficiency_score DECIMAL(5,4) DEFAULT 0.5,

    -- Jarvis can override
    jarvis_boost DECIMAL(3,2) DEFAULT 0.0,  -- +/- adjustment to efficiency
    boost_reason TEXT,

    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_type, model_id, context_type)
);

CREATE INDEX IF NOT EXISTS idx_model_learning_task ON jarvis_model_learning(task_type);
CREATE INDEX IF NOT EXISTS idx_model_learning_model ON jarvis_model_learning(model_id);

-- ============================================================
-- 4. SELECTION DECISION RULES (konfigurierbar)
-- ============================================================

CREATE TABLE IF NOT EXISTS jarvis_selection_rules (
    id SERIAL PRIMARY KEY,
    rule_name VARCHAR(100) NOT NULL UNIQUE,
    rule_type VARCHAR(30) NOT NULL,  -- 'complexity_threshold', 'cost_limit', 'provider_preference', 'time_based'

    -- Condition (JSON for flexibility)
    condition JSONB NOT NULL,  -- e.g., {"complexity_max": 0.3} or {"hour_start": 22, "hour_end": 6}

    -- Action
    action_type VARCHAR(30) NOT NULL,  -- 'prefer_model', 'prefer_provider', 'set_cost_sensitivity', 'boost_capability'
    action_value JSONB NOT NULL,       -- e.g., {"provider": "anthropic"} or {"cost_sensitivity": 0.9}

    priority INTEGER DEFAULT 50,  -- Lower = higher priority
    is_active BOOLEAN DEFAULT TRUE,

    -- Tracking
    times_applied INTEGER DEFAULT 0,
    last_applied TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 5. EXTEND MODEL REGISTRY
-- ============================================================

ALTER TABLE jarvis_model_registry
    ADD COLUMN IF NOT EXISTS specialties TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS best_contexts TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS efficiency_score DECIMAL(5,4) DEFAULT 0.5,
    ADD COLUMN IF NOT EXISTS last_efficiency_update TIMESTAMP,
    ADD COLUMN IF NOT EXISTS total_uses INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS avg_quality_score DECIMAL(5,4);

-- ============================================================
-- 6. SEED DATA: Task Patterns (from current hardcoded)
-- ============================================================

-- Code Generation
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('code_generation', '\b(write|create|generate|implement|build)\b.*\b(code|function|class|script|program)\b', 'regex', 'en', 0.85, 'seed'),
    ('code_generation', '\b(schreibe|erstelle|generiere|implementiere)\b.*\b(code|funktion|klasse|skript)\b', 'regex', 'de', 0.85, 'seed'),
    ('code_generation', '\b(python|javascript|typescript|rust|go|java|c\+\+)\b.*\b(code|function|funktion)\b', 'regex', 'both', 0.90, 'seed'),
    ('code_generation', 'programmiere', 'keyword', 'de', 0.80, 'seed'),
    ('code_generation', 'coding', 'keyword', 'both', 0.75, 'seed')
ON CONFLICT DO NOTHING;

-- Code Review
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('code_review', '\b(review|check|improve|refactor|optimize)\b.*\b(code|function|class)\b', 'regex', 'en', 0.85, 'seed'),
    ('code_review', '\bcode\s*review\b', 'regex', 'both', 0.95, 'seed'),
    ('code_review', '\b(überprüfe|verbessere|optimiere)\b.*\b(code|funktion)\b', 'regex', 'de', 0.85, 'seed'),
    ('code_review', 'refactoring', 'keyword', 'both', 0.80, 'seed')
ON CONFLICT DO NOTHING;

-- Debugging
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('debugging', '\b(debug|fix|error|bug|issue|problem|broken)\b', 'regex', 'en', 0.80, 'seed'),
    ('debugging', '\b(fehler|bug|problem|kaputt|funktioniert nicht)\b', 'regex', 'de', 0.80, 'seed'),
    ('debugging', '\b(doesn''t|does not|won''t|will not)\s*work\b', 'regex', 'en', 0.85, 'seed'),
    ('debugging', 'traceback', 'keyword', 'both', 0.90, 'seed'),
    ('debugging', 'exception', 'keyword', 'both', 0.85, 'seed'),
    ('debugging', 'stacktrace', 'keyword', 'both', 0.90, 'seed')
ON CONFLICT DO NOTHING;

-- Math/Reasoning
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('math_reasoning', '\b(calculate|compute|solve|prove|equation|formula)\b', 'regex', 'en', 0.85, 'seed'),
    ('math_reasoning', '\b(berechne|löse|gleichung|formel)\b', 'regex', 'de', 0.85, 'seed'),
    ('math_reasoning', '\b(math|mathematical|algebra|calculus|geometry)\b', 'regex', 'en', 0.80, 'seed'),
    ('math_reasoning', '\d+\s*[\+\-\*\/\^]\s*\d+', 'regex', 'both', 0.70, 'seed'),
    ('math_reasoning', 'integral', 'keyword', 'both', 0.90, 'seed'),
    ('math_reasoning', 'derivative', 'keyword', 'both', 0.90, 'seed')
ON CONFLICT DO NOTHING;

-- Analysis
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('analysis', '\b(analyze|analyse|evaluate|assess|compare)\b', 'regex', 'en', 0.80, 'seed'),
    ('analysis', '\b(analysiere|analysieren|auswerten|bewerten|vergleichen)\b', 'regex', 'de', 0.85, 'seed'),
    ('analysis', '\b(data|statistics|metrics|trends)\b', 'regex', 'en', 0.75, 'seed'),
    ('analysis', '\b(daten|statistik|metriken|performance|bericht|report)\b', 'regex', 'de', 0.80, 'seed'),
    ('analysis', 'zusammenfassung', 'keyword', 'de', 0.75, 'seed'),
    ('analysis', 'insights', 'keyword', 'both', 0.80, 'seed')
ON CONFLICT DO NOTHING;

-- Creative Writing
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('creative_writing', '\b(write|create)\b.*\b(story|poem|essay|article|blog)\b', 'regex', 'en', 0.85, 'seed'),
    ('creative_writing', '\b(schreibe|verfasse)\b.*\b(geschichte|gedicht|artikel)\b', 'regex', 'de', 0.85, 'seed'),
    ('creative_writing', '\b(creative|imaginative|fictional)\b', 'regex', 'en', 0.75, 'seed'),
    ('creative_writing', 'kreativ', 'keyword', 'de', 0.70, 'seed')
ON CONFLICT DO NOTHING;

-- Planning
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('planning', '\b(plan|strategy|roadmap|schedule|timeline)\b', 'regex', 'en', 0.80, 'seed'),
    ('planning', '\b(plane|strategie|zeitplan)\b', 'regex', 'de', 0.80, 'seed'),
    ('planning', '\b(how\s+should|what\s+steps)\b', 'regex', 'en', 0.75, 'seed'),
    ('planning', '\b(wie\s+soll|welche\s+schritte)\b', 'regex', 'de', 0.75, 'seed'),
    ('planning', 'roadmap', 'keyword', 'both', 0.85, 'seed')
ON CONFLICT DO NOTHING;

-- Summarization
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('summarization', '\b(summarize|summarise|summary|tldr|brief)\b', 'regex', 'en', 0.90, 'seed'),
    ('summarization', '\b(zusammenfassen|zusammenfassung|kurzfassung)\b', 'regex', 'de', 0.90, 'seed'),
    ('summarization', '\b(key\s+points|main\s+points|highlights)\b', 'regex', 'en', 0.85, 'seed'),
    ('summarization', 'kernpunkte', 'keyword', 'de', 0.85, 'seed')
ON CONFLICT DO NOTHING;

-- Translation
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('translation', '\b(translate|translation)\b', 'regex', 'en', 0.95, 'seed'),
    ('translation', '\b(übersetze|übersetzung)\b', 'regex', 'de', 0.95, 'seed'),
    ('translation', '\b(to\s+english|to\s+german|ins\s+deutsche|ins\s+englische)\b', 'regex', 'both', 0.90, 'seed'),
    ('translation', 'auf deutsch', 'phrase', 'de', 0.85, 'seed')
ON CONFLICT DO NOTHING;

-- Quick Question
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('quick_question', '^(what|who|when|where|why|how)\s+(is|are|was|were|do|does|did)\b', 'regex', 'en', 0.70, 'seed'),
    ('quick_question', '^(was|wer|wann|wo|warum|wie)\s+(ist|sind|war|waren)\b', 'regex', 'de', 0.70, 'seed'),
    ('quick_question', '\?$', 'regex', 'both', 0.50, 'seed')
ON CONFLICT DO NOTHING;

-- General Chat
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('general_chat', '^(hi|hello|hey|hallo|guten\s+tag|guten\s+morgen|good\s+morning)[\s\!\.\,]*$', 'regex', 'both', 0.95, 'seed'),
    ('general_chat', '^(thanks|thank\s+you|danke|vielen\s+dank)[\s\!\.\,]*$', 'regex', 'both', 0.95, 'seed'),
    ('general_chat', '^(bye|goodbye|tschüss|ciao|bis\s+später)[\s\!\.\,]*$', 'regex', 'both', 0.95, 'seed'),
    ('general_chat', '^wie\s+geht.*\?*$', 'regex', 'de', 0.90, 'seed'),
    ('general_chat', '^how\s+are\s+you.*\?*$', 'regex', 'en', 0.90, 'seed')
ON CONFLICT DO NOTHING;

-- Tool Execution
INSERT INTO jarvis_task_patterns (task_type, pattern_text, pattern_type, language, confidence, source) VALUES
    ('tool_execution', '\b(search|find|lookup|query|fetch)\b.*\b(in|from|using)\b', 'regex', 'en', 0.75, 'seed'),
    ('tool_execution', '\b(suche|finde|hole)\b.*\b(in|aus|von)\b', 'regex', 'de', 0.75, 'seed'),
    ('tool_execution', '\b(send|post|create|delete|update)\b.*\b(to|in|from)\b', 'regex', 'en', 0.70, 'seed'),
    ('tool_execution', 'api call', 'phrase', 'both', 0.85, 'seed')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 7. SEED DATA: Complexity Patterns
-- ============================================================

-- High Complexity Indicators
INSERT INTO jarvis_complexity_patterns (indicator_type, pattern_text, pattern_type, weight, source) VALUES
    ('high', '\b(complex|complicated|difficult|advanced|sophisticated)\b', 'regex', 0.20, 'seed'),
    ('high', '\b(komplex|kompliziert|schwierig|umfangreich|anspruchsvoll)\b', 'regex', 0.20, 'seed'),
    ('high', '\b(multiple|several|various|many)\b.*\b(files|functions|systems|components)\b', 'regex', 0.25, 'seed'),
    ('high', '\b(mehrere|verschiedene|viele)\b.*\b(dateien|funktionen|systeme)\b', 'regex', 0.25, 'seed'),
    ('high', '\b(architecture|infrastructure|deployment|migration)\b', 'regex', 0.20, 'seed'),
    ('high', '\b(architektur|infrastruktur|deployment)\b', 'regex', 0.20, 'seed'),
    ('high', '\b(security|authentication|encryption|authorization)\b', 'regex', 0.20, 'seed'),
    ('high', '\b(sicherheit|authentifizierung|verschlüsselung)\b', 'regex', 0.20, 'seed'),
    ('high', '\b(refactor|redesign|overhaul|rewrite)\b', 'regex', 0.25, 'seed'),
    ('high', '\b(performance|optimization|scalability)\b', 'regex', 0.15, 'seed'),
    ('high', '\b(full|complete|comprehensive|entire)\b.*\b(analysis|review|report)\b', 'regex', 0.20, 'seed')
ON CONFLICT DO NOTHING;

-- Low Complexity Indicators
INSERT INTO jarvis_complexity_patterns (indicator_type, pattern_text, pattern_type, weight, source) VALUES
    ('low', '\b(simple|basic|easy|quick|short|small)\b', 'regex', 0.20, 'seed'),
    ('low', '\b(einfach|kurz|schnell|klein|simpel)\b', 'regex', 0.20, 'seed'),
    ('low', '\b(just|only|single|one)\b', 'regex', 0.15, 'seed'),
    ('low', '\b(nur|einzeln|ein|eines)\b', 'regex', 0.15, 'seed'),
    ('low', '^.{0,40}$', 'regex', 0.15, 'seed'),  -- Very short queries
    ('low', '^.{0,20}\?$', 'regex', 0.20, 'seed'),  -- Short questions
    ('low', '\b(briefly|quickly|fast)\b', 'regex', 0.15, 'seed'),
    ('low', '\b(kurz|mal\s+eben|schnell)\b', 'regex', 0.15, 'seed')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 8. SEED DATA: Selection Rules
-- ============================================================

INSERT INTO jarvis_selection_rules (rule_name, rule_type, condition, action_type, action_value, priority, is_active) VALUES
    -- Low complexity → cheapest model
    ('low_complexity_cheap', 'complexity_threshold',
     '{"complexity_max": 0.3}',
     'set_cost_sensitivity', '{"value": 0.95}',
     10, TRUE),

    -- High complexity → quality focus
    ('high_complexity_quality', 'complexity_threshold',
     '{"complexity_min": 0.7}',
     'set_cost_sensitivity', '{"value": 0.3}',
     10, TRUE),

    -- Night time → prefer fast/cheap models
    ('night_time_cheap', 'time_based',
     '{"hour_start": 23, "hour_end": 6}',
     'prefer_provider', '{"provider": "openai", "reason": "cheaper for late night casual work"}',
     30, TRUE),

    -- Code tasks → prefer Anthropic
    ('code_prefer_anthropic', 'task_type_match',
     '{"task_types": ["code_generation", "code_review", "debugging"]}',
     'prefer_provider', '{"provider": "anthropic", "reason": "better code understanding"}',
     20, TRUE),

    -- Math → prefer o1/o3
    ('math_prefer_reasoning', 'task_type_match',
     '{"task_types": ["math_reasoning"]}',
     'prefer_model', '{"models": ["o1-mini", "o3-mini", "o1"], "reason": "reasoning-optimized"}',
     15, TRUE),

    -- Simple chat → always cheapest
    ('chat_always_cheap', 'task_type_match',
     '{"task_types": ["general_chat", "quick_question"]}',
     'set_cost_sensitivity', '{"value": 0.99}',
     5, TRUE)
ON CONFLICT (rule_name) DO NOTHING;

-- ============================================================
-- 9. ADD MORE MODELS
-- ============================================================

-- OpenAI Models
INSERT INTO jarvis_model_registry (model_id, provider, display_name, cost_input_per_1m, cost_output_per_1m, cap_reasoning, cap_coding, cap_creative, cap_analysis, cap_math, cap_speed, max_tokens, context_window, notes, specialties)
VALUES
    ('gpt-4.5-preview', 'openai', 'GPT-4.5 Preview', 75.00, 150.00, 0.98, 0.95, 0.93, 0.98, 0.95, 0.35, 16384, 128000, 'Newest flagship, very expensive', ARRAY['complex_reasoning', 'research']),
    ('o3-mini', 'openai', 'o3-mini', 1.10, 4.40, 0.93, 0.78, 0.55, 0.92, 0.97, 0.70, 65536, 128000, 'Best value for reasoning', ARRAY['math', 'logic', 'reasoning']),
    ('gpt-4o-2024-11-20', 'openai', 'GPT-4o (Nov 2024)', 2.50, 10.00, 0.91, 0.86, 0.86, 0.91, 0.86, 0.78, 16384, 128000, 'Stable Nov snapshot', ARRAY['general', 'balanced'])
ON CONFLICT (model_id) DO UPDATE SET
    cost_input_per_1m = EXCLUDED.cost_input_per_1m,
    cost_output_per_1m = EXCLUDED.cost_output_per_1m,
    specialties = EXCLUDED.specialties,
    updated_at = CURRENT_TIMESTAMP;

-- Anthropic Models
INSERT INTO jarvis_model_registry (model_id, provider, display_name, cost_input_per_1m, cost_output_per_1m, cap_reasoning, cap_coding, cap_creative, cap_analysis, cap_math, cap_speed, max_tokens, context_window, notes, specialties)
VALUES
    ('claude-sonnet-4-6-20260101', 'anthropic', 'Claude Sonnet 4.6', 3.00, 15.00, 0.94, 0.97, 0.92, 0.94, 0.88, 0.72, 8192, 200000, 'Latest Sonnet, best for code', ARRAY['coding', 'analysis']),
    ('claude-opus-4-6-20260101', 'anthropic', 'Claude Opus 4.6', 15.00, 75.00, 0.99, 0.98, 0.96, 0.99, 0.94, 0.45, 8192, 200000, 'Latest Opus, most capable', ARRAY['complex_reasoning', 'research', 'coding'])
ON CONFLICT (model_id) DO UPDATE SET
    cost_input_per_1m = EXCLUDED.cost_input_per_1m,
    cost_output_per_1m = EXCLUDED.cost_output_per_1m,
    specialties = EXCLUDED.specialties,
    updated_at = CURRENT_TIMESTAMP;

-- Update existing models with specialties
UPDATE jarvis_model_registry SET specialties = ARRAY['fast', 'cheap', 'general'] WHERE model_id = 'gpt-4o-mini';
UPDATE jarvis_model_registry SET specialties = ARRAY['fast', 'cheap'] WHERE model_id = 'claude-haiku-4-5-20251001';
UPDATE jarvis_model_registry SET specialties = ARRAY['coding', 'analysis', 'balanced'] WHERE model_id = 'claude-sonnet-4-20250514';
UPDATE jarvis_model_registry SET specialties = ARRAY['math', 'reasoning'] WHERE model_id = 'o1-mini';
UPDATE jarvis_model_registry SET specialties = ARRAY['math', 'reasoning', 'research'] WHERE model_id = 'o1';

-- ============================================================
-- 10. PATTERN LEARNING LOG (für Transparenz)
-- ============================================================

CREATE TABLE IF NOT EXISTS jarvis_pattern_learning_log (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(30) NOT NULL,  -- 'pattern_added', 'pattern_updated', 'pattern_disabled', 'rule_changed'
    table_name VARCHAR(50) NOT NULL,
    record_id INTEGER,
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    initiated_by VARCHAR(50) DEFAULT 'jarvis',  -- 'jarvis', 'system', 'user'
    confidence DECIMAL(5,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pattern_learning_action ON jarvis_pattern_learning_log(action_type);
CREATE INDEX IF NOT EXISTS idx_pattern_learning_created ON jarvis_pattern_learning_log(created_at);
