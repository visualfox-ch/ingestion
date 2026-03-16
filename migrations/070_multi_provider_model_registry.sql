-- Migration: Multi-Provider Model Registry
-- Phase 21: Autonomous Model Selection
-- Jarvis can read and modify these tables to optimize model usage

-- Available models from all providers
CREATE TABLE IF NOT EXISTS jarvis_model_registry (
    model_id VARCHAR(100) PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,  -- 'openai', 'anthropic'
    display_name VARCHAR(100) NOT NULL,

    -- Pricing (USD per 1M tokens)
    cost_input_per_1m DECIMAL(10, 4) NOT NULL,
    cost_output_per_1m DECIMAL(10, 4) NOT NULL,

    -- Capabilities (0.0 - 1.0 scores)
    cap_reasoning DECIMAL(3, 2) DEFAULT 0.5,
    cap_coding DECIMAL(3, 2) DEFAULT 0.5,
    cap_creative DECIMAL(3, 2) DEFAULT 0.5,
    cap_analysis DECIMAL(3, 2) DEFAULT 0.5,
    cap_math DECIMAL(3, 2) DEFAULT 0.5,
    cap_speed DECIMAL(3, 2) DEFAULT 0.5,  -- Higher = faster

    -- Limits
    max_tokens INTEGER DEFAULT 4096,
    context_window INTEGER DEFAULT 128000,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,  -- Only one should be default

    -- Metadata
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Task type definitions
CREATE TABLE IF NOT EXISTS jarvis_task_types (
    task_type VARCHAR(50) PRIMARY KEY,
    description TEXT,

    -- Required capability weights (which capabilities matter most)
    weight_reasoning DECIMAL(3, 2) DEFAULT 0.5,
    weight_coding DECIMAL(3, 2) DEFAULT 0.0,
    weight_creative DECIMAL(3, 2) DEFAULT 0.0,
    weight_analysis DECIMAL(3, 2) DEFAULT 0.5,
    weight_math DECIMAL(3, 2) DEFAULT 0.0,
    weight_speed DECIMAL(3, 2) DEFAULT 0.5,

    -- Cost sensitivity (0 = don't care, 1 = very cost sensitive)
    cost_sensitivity DECIMAL(3, 2) DEFAULT 0.7,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Task-to-Model mapping (Jarvis can override)
CREATE TABLE IF NOT EXISTS jarvis_task_model_mapping (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) REFERENCES jarvis_task_types(task_type),
    model_id VARCHAR(100) REFERENCES jarvis_model_registry(model_id),
    priority INTEGER DEFAULT 1,  -- Lower = higher priority

    -- Conditions for using this model
    min_complexity DECIMAL(3, 2) DEFAULT 0.0,  -- 0-1
    max_complexity DECIMAL(3, 2) DEFAULT 1.0,

    -- Jarvis learning
    times_used INTEGER DEFAULT 0,
    success_rate DECIMAL(5, 4) DEFAULT 0.0,
    avg_latency_ms INTEGER DEFAULT 0,

    -- Override by Jarvis
    jarvis_override BOOLEAN DEFAULT FALSE,
    override_reason TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(task_type, model_id)
);

-- Model usage history for learning
CREATE TABLE IF NOT EXISTS jarvis_model_usage_log (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(100) REFERENCES jarvis_model_registry(model_id),
    task_type VARCHAR(50),
    query_preview VARCHAR(200),

    -- Performance
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd DECIMAL(10, 6),

    -- Quality (can be updated later)
    success BOOLEAN DEFAULT TRUE,
    quality_score DECIMAL(3, 2),  -- 0-1, can be set by feedback

    -- Context
    user_id VARCHAR(100),
    session_id VARCHAR(100),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for analytics
CREATE INDEX IF NOT EXISTS idx_model_usage_model ON jarvis_model_usage_log(model_id);
CREATE INDEX IF NOT EXISTS idx_model_usage_task ON jarvis_model_usage_log(task_type);
CREATE INDEX IF NOT EXISTS idx_model_usage_created ON jarvis_model_usage_log(created_at);

-- ============================================================
-- DEFAULT DATA: Initial model registry
-- ============================================================

-- OpenAI Models
INSERT INTO jarvis_model_registry (model_id, provider, display_name, cost_input_per_1m, cost_output_per_1m, cap_reasoning, cap_coding, cap_creative, cap_analysis, cap_math, cap_speed, max_tokens, context_window, is_default, notes)
VALUES
    ('gpt-4o-mini', 'openai', 'GPT-4o Mini', 0.15, 0.60, 0.70, 0.65, 0.70, 0.65, 0.60, 0.95, 16384, 128000, TRUE, 'Cheapest, fastest - default for simple tasks'),
    ('gpt-4o', 'openai', 'GPT-4o', 2.50, 10.00, 0.90, 0.85, 0.85, 0.90, 0.85, 0.80, 16384, 128000, FALSE, 'Best OpenAI all-rounder'),
    ('gpt-4-turbo', 'openai', 'GPT-4 Turbo', 10.00, 30.00, 0.92, 0.90, 0.88, 0.92, 0.90, 0.60, 4096, 128000, FALSE, 'Legacy but very capable'),
    ('o1-mini', 'openai', 'o1-mini', 3.00, 12.00, 0.95, 0.80, 0.60, 0.95, 0.98, 0.40, 65536, 128000, FALSE, 'Best for math/reasoning, slower'),
    ('o1', 'openai', 'o1', 15.00, 60.00, 0.99, 0.85, 0.70, 0.98, 0.99, 0.30, 100000, 200000, FALSE, 'Top reasoning, expensive')
ON CONFLICT (model_id) DO UPDATE SET
    cost_input_per_1m = EXCLUDED.cost_input_per_1m,
    cost_output_per_1m = EXCLUDED.cost_output_per_1m,
    updated_at = CURRENT_TIMESTAMP;

-- Anthropic Models
INSERT INTO jarvis_model_registry (model_id, provider, display_name, cost_input_per_1m, cost_output_per_1m, cap_reasoning, cap_coding, cap_creative, cap_analysis, cap_math, cap_speed, max_tokens, context_window, notes)
VALUES
    ('claude-haiku-4-5-20251001', 'anthropic', 'Claude Haiku 4.5', 0.25, 1.25, 0.75, 0.70, 0.75, 0.70, 0.65, 0.95, 8192, 200000, 'Fast Anthropic option'),
    ('claude-sonnet-4-20250514', 'anthropic', 'Claude Sonnet 4', 3.00, 15.00, 0.92, 0.95, 0.90, 0.92, 0.85, 0.70, 8192, 200000, 'Best coding, great all-rounder'),
    ('claude-opus-4-5-20251101', 'anthropic', 'Claude Opus 4.5', 15.00, 75.00, 0.98, 0.97, 0.95, 0.98, 0.92, 0.50, 8192, 200000, 'Top Anthropic model, expensive')
ON CONFLICT (model_id) DO UPDATE SET
    cost_input_per_1m = EXCLUDED.cost_input_per_1m,
    cost_output_per_1m = EXCLUDED.cost_output_per_1m,
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================
-- DEFAULT DATA: Task types
-- ============================================================

INSERT INTO jarvis_task_types (task_type, description, weight_reasoning, weight_coding, weight_creative, weight_analysis, weight_math, weight_speed, cost_sensitivity)
VALUES
    ('general_chat', 'Simple conversation, greetings, small talk', 0.3, 0.0, 0.3, 0.2, 0.0, 0.9, 0.9),
    ('quick_question', 'Simple factual questions', 0.4, 0.0, 0.1, 0.3, 0.1, 0.9, 0.9),
    ('code_generation', 'Writing new code', 0.6, 1.0, 0.3, 0.5, 0.3, 0.5, 0.5),
    ('code_review', 'Reviewing and improving code', 0.7, 0.9, 0.2, 0.8, 0.2, 0.4, 0.4),
    ('debugging', 'Finding and fixing bugs', 0.8, 0.95, 0.1, 0.9, 0.3, 0.3, 0.3),
    ('analysis', 'Data analysis, research', 0.8, 0.4, 0.2, 1.0, 0.5, 0.4, 0.5),
    ('creative_writing', 'Stories, poems, creative content', 0.5, 0.0, 1.0, 0.3, 0.0, 0.5, 0.6),
    ('math_reasoning', 'Complex math, logic puzzles', 0.95, 0.3, 0.1, 0.7, 1.0, 0.2, 0.2),
    ('planning', 'Project planning, strategy', 0.85, 0.3, 0.4, 0.8, 0.2, 0.4, 0.4),
    ('summarization', 'Summarizing text, documents', 0.5, 0.0, 0.3, 0.7, 0.0, 0.8, 0.7),
    ('translation', 'Language translation', 0.4, 0.0, 0.5, 0.3, 0.0, 0.8, 0.7),
    ('tool_execution', 'Running tools, API calls', 0.6, 0.7, 0.1, 0.5, 0.2, 0.7, 0.6)
ON CONFLICT (task_type) DO NOTHING;

-- ============================================================
-- DEFAULT DATA: Task-to-Model mappings
-- ============================================================

-- General chat / Quick questions -> GPT-4o-mini (cheapest)
INSERT INTO jarvis_task_model_mapping (task_type, model_id, priority, max_complexity)
VALUES
    ('general_chat', 'gpt-4o-mini', 1, 0.5),
    ('general_chat', 'claude-haiku-4-5-20251001', 2, 0.7),
    ('general_chat', 'gpt-4o', 3, 1.0),

    ('quick_question', 'gpt-4o-mini', 1, 0.5),
    ('quick_question', 'claude-haiku-4-5-20251001', 2, 0.7),
    ('quick_question', 'gpt-4o', 3, 1.0)
ON CONFLICT (task_type, model_id) DO NOTHING;

-- Code tasks -> Claude Sonnet (best for coding)
INSERT INTO jarvis_task_model_mapping (task_type, model_id, priority, max_complexity)
VALUES
    ('code_generation', 'gpt-4o-mini', 1, 0.3),
    ('code_generation', 'claude-sonnet-4-20250514', 2, 0.8),
    ('code_generation', 'claude-opus-4-5-20251101', 3, 1.0),

    ('code_review', 'claude-haiku-4-5-20251001', 1, 0.4),
    ('code_review', 'claude-sonnet-4-20250514', 2, 0.8),
    ('code_review', 'claude-opus-4-5-20251101', 3, 1.0),

    ('debugging', 'claude-sonnet-4-20250514', 1, 0.7),
    ('debugging', 'claude-opus-4-5-20251101', 2, 1.0)
ON CONFLICT (task_type, model_id) DO NOTHING;

-- Math/Reasoning -> o1 models
INSERT INTO jarvis_task_model_mapping (task_type, model_id, priority, max_complexity)
VALUES
    ('math_reasoning', 'gpt-4o-mini', 1, 0.3),
    ('math_reasoning', 'o1-mini', 2, 0.7),
    ('math_reasoning', 'o1', 3, 1.0),

    ('analysis', 'gpt-4o-mini', 1, 0.3),
    ('analysis', 'gpt-4o', 2, 0.6),
    ('analysis', 'claude-sonnet-4-20250514', 3, 1.0)
ON CONFLICT (task_type, model_id) DO NOTHING;

-- Creative -> GPT-4o or Claude
INSERT INTO jarvis_task_model_mapping (task_type, model_id, priority, max_complexity)
VALUES
    ('creative_writing', 'gpt-4o-mini', 1, 0.4),
    ('creative_writing', 'gpt-4o', 2, 0.7),
    ('creative_writing', 'claude-sonnet-4-20250514', 3, 1.0),

    ('planning', 'gpt-4o-mini', 1, 0.3),
    ('planning', 'gpt-4o', 2, 0.6),
    ('planning', 'claude-sonnet-4-20250514', 3, 1.0)
ON CONFLICT (task_type, model_id) DO NOTHING;

-- Fast tasks -> Mini models
INSERT INTO jarvis_task_model_mapping (task_type, model_id, priority, max_complexity)
VALUES
    ('summarization', 'gpt-4o-mini', 1, 0.6),
    ('summarization', 'claude-haiku-4-5-20251001', 2, 0.8),
    ('summarization', 'gpt-4o', 3, 1.0),

    ('translation', 'gpt-4o-mini', 1, 0.7),
    ('translation', 'gpt-4o', 2, 1.0),

    ('tool_execution', 'gpt-4o-mini', 1, 0.4),
    ('tool_execution', 'claude-haiku-4-5-20251001', 2, 0.6),
    ('tool_execution', 'claude-sonnet-4-20250514', 3, 1.0)
ON CONFLICT (task_type, model_id) DO NOTHING;
