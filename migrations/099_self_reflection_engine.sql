-- Phase A1: Self-Reflection Engine
-- Based on Reflexion (Shinn et al. 2023) - Verbal Reinforcement Learning
-- Date: 2026-03-15

-- Reflection log: stores evaluation and reflections for each interaction
CREATE TABLE IF NOT EXISTS reflection_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    query_hash VARCHAR(64),
    query_summary TEXT,
    response_quality FLOAT DEFAULT 0.5,  -- 0-1 scale
    critique_scores JSONB DEFAULT '{}',  -- {rule_name: score}
    reflection TEXT,                      -- "What could be better?"
    improvements_identified JSONB DEFAULT '[]',  -- [{type, description, priority}]
    improvements_applied BOOLEAN DEFAULT FALSE,
    learning_extracted BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Self-critique rules: configurable evaluation criteria
CREATE TABLE IF NOT EXISTS self_critique_rules (
    id SERIAL PRIMARY KEY,
    rule_name VARCHAR(100) NOT NULL UNIQUE,
    rule_category VARCHAR(50) NOT NULL,  -- accuracy, helpfulness, safety, efficiency, style
    rule_condition TEXT,                  -- When to apply (SQL-like condition or keyword match)
    critique_prompt TEXT NOT NULL,        -- How to evaluate (prompt for self-critique)
    weight FLOAT DEFAULT 1.0,
    min_score_threshold FLOAT DEFAULT 0.5,  -- Below this triggers reflection
    is_active BOOLEAN DEFAULT TRUE,
    examples JSONB DEFAULT '[]',          -- Example good/bad responses
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reflection improvements: extracted learnings ready for application
CREATE TABLE IF NOT EXISTS reflection_improvements (
    id SERIAL PRIMARY KEY,
    reflection_id INTEGER REFERENCES reflection_log(id),
    improvement_type VARCHAR(50) NOT NULL,  -- tool_usage, response_format, knowledge_gap, reasoning, style
    description TEXT NOT NULL,
    action_required TEXT,                   -- Concrete action to take
    priority VARCHAR(20) DEFAULT 'medium',  -- low, medium, high, critical
    status VARCHAR(20) DEFAULT 'pending',   -- pending, in_progress, applied, dismissed
    applied_at TIMESTAMPTZ,
    outcome_verified BOOLEAN DEFAULT FALSE,
    outcome_score FLOAT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reflection metrics: track improvement over time
CREATE TABLE IF NOT EXISTS reflection_metrics (
    id SERIAL PRIMARY KEY,
    metric_date DATE NOT NULL,
    metric_type VARCHAR(50) NOT NULL,  -- daily_quality, rule_compliance, improvement_rate
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    sample_size INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(metric_date, metric_type, metric_name)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_reflection_log_session ON reflection_log(session_id);
CREATE INDEX IF NOT EXISTS idx_reflection_log_created ON reflection_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reflection_log_quality ON reflection_log(response_quality);
CREATE INDEX IF NOT EXISTS idx_reflection_improvements_status ON reflection_improvements(status);
CREATE INDEX IF NOT EXISTS idx_reflection_improvements_type ON reflection_improvements(improvement_type);
CREATE INDEX IF NOT EXISTS idx_reflection_metrics_date ON reflection_metrics(metric_date DESC);

-- Insert default self-critique rules
INSERT INTO self_critique_rules (rule_name, rule_category, rule_condition, critique_prompt, weight) VALUES
-- Accuracy rules
('factual_accuracy', 'accuracy', 'all',
 'Did the response contain any factually incorrect statements? Rate accuracy from 0-1.', 1.5),
('tool_correctness', 'accuracy', 'tool_call',
 'Were the correct tools used with appropriate parameters? Rate from 0-1.', 1.2),

-- Helpfulness rules
('task_completion', 'helpfulness', 'all',
 'Did the response fully address the user''s request? Rate completeness from 0-1.', 1.3),
('actionability', 'helpfulness', 'all',
 'Was the response actionable and practical? Rate from 0-1.', 1.0),
('relevance', 'helpfulness', 'all',
 'Was all information in the response relevant to the query? Rate from 0-1.', 1.0),

-- Efficiency rules
('conciseness', 'efficiency', 'all',
 'Was the response appropriately concise without unnecessary verbosity? Rate from 0-1.', 0.8),
('tool_efficiency', 'efficiency', 'tool_call',
 'Were tools used efficiently without unnecessary calls? Rate from 0-1.', 0.9),

-- Style rules
('tone_appropriateness', 'style', 'all',
 'Was the tone appropriate for the context and user relationship? Rate from 0-1.', 0.7),
('clarity', 'style', 'all',
 'Was the response clear and easy to understand? Rate from 0-1.', 0.9),

-- Safety rules
('safety_check', 'safety', 'all',
 'Did the response avoid harmful, biased, or inappropriate content? Rate from 0-1.', 2.0),
('privacy_respect', 'safety', 'personal_info',
 'Did the response appropriately handle personal or sensitive information? Rate from 0-1.', 1.8)
ON CONFLICT (rule_name) DO NOTHING;

-- Comment
COMMENT ON TABLE reflection_log IS 'Phase A1: Stores self-reflection evaluations for continuous improvement';
COMMENT ON TABLE self_critique_rules IS 'Phase A1: Configurable rules for self-evaluation';
COMMENT ON TABLE reflection_improvements IS 'Phase A1: Extracted improvements from reflections';
COMMENT ON TABLE reflection_metrics IS 'Phase A1: Tracks improvement metrics over time';

-- Register Self-Reflection Tools in jarvis_tools
INSERT INTO jarvis_tools (name, description, category, is_enabled, requires_approval, parameters, keywords) VALUES
('evaluate_my_response', 'Evaluate a response against self-critique rules', 'self_reflection', TRUE, FALSE,
 '{"query": "string", "response": "string", "tool_calls": "array", "session_id": "string"}',
 ARRAY['evaluate', 'bewerten', 'quality', 'qualität']),
('reflect_on_response', 'Generate reflection and improvements for a response', 'self_reflection', TRUE, FALSE,
 '{"reflection_id": "integer", "query": "string", "response": "string", "critique_scores": "object"}',
 ARRAY['reflect', 'reflektieren', 'improve', 'verbessern']),
('get_my_learnings', 'Extract learnings from accumulated reflections', 'self_reflection', TRUE, FALSE,
 '{"days": "integer", "min_occurrences": "integer"}',
 ARRAY['learnings', 'lernfortschritt', 'what learned']),
('get_improvement_progress', 'Get metrics on self-improvement over time', 'self_reflection', TRUE, FALSE,
 '{"days": "integer"}',
 ARRAY['progress', 'fortschritt', 'metrics', 'trend']),
('get_pending_improvements', 'Get pending improvements waiting to be applied', 'self_reflection', TRUE, FALSE,
 '{"priority": "string", "limit": "integer"}',
 ARRAY['pending', 'ausstehend', 'improvements']),
('apply_improvement', 'Mark an improvement as applied', 'self_reflection', TRUE, TRUE,
 '{"improvement_id": "integer", "outcome_score": "number"}',
 ARRAY['apply', 'anwenden', 'improvement']),
('run_self_reflection', 'Run the full self-reflection loop', 'self_reflection', TRUE, FALSE,
 '{"query": "string", "response": "string", "tool_calls": "array", "session_id": "string"}',
 ARRAY['self-reflection', 'selbstreflexion', 'full loop']),
('add_critique_rule', 'Add or update a self-critique rule', 'self_reflection', TRUE, TRUE,
 '{"rule_name": "string", "rule_category": "string", "critique_prompt": "string", "weight": "number"}',
 ARRAY['critique', 'kritik', 'rule', 'regel']),
('get_critique_rules', 'Get all self-critique rules', 'self_reflection', TRUE, FALSE,
 '{"category": "string", "active_only": "boolean"}',
 ARRAY['critique rules', 'kritikregeln', 'evaluation'])
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    parameters = EXCLUDED.parameters,
    keywords = EXCLUDED.keywords;
