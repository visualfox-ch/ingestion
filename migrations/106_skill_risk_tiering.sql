-- Phase L0.1: Skill Risk-Tiering
-- Formal categorization of all tools by risk level
-- Extends the Leitplanken-System with granular tool control
-- Date: 2026-03-15

-- Add risk_tier column to jarvis_tools
ALTER TABLE jarvis_tools
ADD COLUMN IF NOT EXISTS risk_tier INTEGER DEFAULT 1
CHECK (risk_tier >= 0 AND risk_tier <= 3);

-- Add tier description
COMMENT ON COLUMN jarvis_tools.risk_tier IS 'Risk tier: 0=always allowed (read-only), 1=confidence>80%, 2=user confirmation, 3=explicit override only';

-- Create tier definitions table for documentation and runtime lookup
CREATE TABLE IF NOT EXISTS tool_risk_tiers (
    tier INTEGER PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    description TEXT,
    requirement TEXT NOT NULL,
    auto_approve BOOLEAN DEFAULT FALSE,
    min_confidence FLOAT,
    requires_confirmation BOOLEAN DEFAULT FALSE,
    requires_override BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert tier definitions
INSERT INTO tool_risk_tiers (tier, name, description, requirement, auto_approve, min_confidence, requires_confirmation, requires_override) VALUES
(0, 'safe', 'Read-only tools with no side effects', 'Always allowed', TRUE, NULL, FALSE, FALSE),
(1, 'standard', 'Normal tools requiring reasonable confidence', 'Confidence >= 80%', FALSE, 0.8, FALSE, FALSE),
(2, 'sensitive', 'Tools that modify state or user data', 'User confirmation required', FALSE, NULL, TRUE, FALSE),
(3, 'critical', 'Tools with irreversible or high-impact effects', 'Explicit override only', FALSE, NULL, FALSE, TRUE)
ON CONFLICT (tier) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    requirement = EXCLUDED.requirement,
    auto_approve = EXCLUDED.auto_approve,
    min_confidence = EXCLUDED.min_confidence,
    requires_confirmation = EXCLUDED.requires_confirmation,
    requires_override = EXCLUDED.requires_override;

-- ============================================
-- Set default tiers for existing tools
-- ============================================

-- Tier 0: Safe (read-only, no side effects)
UPDATE jarvis_tools SET risk_tier = 0 WHERE tool_name IN (
    -- Guardrails read
    'get_guardrails', 'get_audit_log', 'get_guardrails_summary',
    -- Memory read
    'recall_memory', 'search_memories', 'get_memory_stats', 'get_working_context',
    -- Facts read
    'get_facts', 'search_facts',
    -- Reflection read
    'get_reflection_history', 'get_learning_patterns',
    -- Uncertainty read
    'get_uncertainty_factors', 'get_calibration_stats',
    -- Causal read
    'get_causal_chain', 'get_causal_summary', 'find_causal_nodes',
    -- Importance read
    'get_important_entities', 'get_importance_factors', 'get_scoring_stats',
    -- Research read
    'get_research_providers',
    -- Identity read
    'get_self_model', 'get_relationship',
    -- General read
    'get_config', 'get_system_status', 'check_guardrails'
);

-- Tier 1: Standard (requires confidence >= 80%)
UPDATE jarvis_tools SET risk_tier = 1 WHERE tool_name IN (
    -- Memory write (non-critical)
    'store_memory', 'promote_to_working', 'demote_memory', 'create_session_summary',
    -- Learning
    'learn_causal_relationship', 'add_causal_node', 'record_intervention',
    -- Scoring
    'score_content_importance', 'retrieve_by_relevance', 'update_entity_importance',
    -- Reflection
    'record_reflection', 'log_experience',
    -- Uncertainty
    'assess_uncertainty', 'record_prediction',
    -- Research
    'web_search', 'research_topic',
    -- Tools with limited impact
    'why_does', 'what_if', 'how_to_achieve'
);

-- Tier 2: Sensitive (requires user confirmation)
UPDATE jarvis_tools SET risk_tier = 2 WHERE tool_name IN (
    -- Persistent memory changes
    'remember_fact', 'archive_memory', 'clear_working_context',
    -- Identity changes
    'evolve_identity', 'update_relationship',
    -- Guardrail management
    'add_guardrail', 'update_guardrail', 'add_guardrail_feedback',
    -- Learning that affects behavior
    'record_learning', 'add_importance_factor',
    -- External communications
    'send_telegram', 'send_email',
    -- Playbook modifications
    'update_playbook', 'add_playbook_phrase'
);

-- Tier 3: Critical (requires explicit override)
UPDATE jarvis_tools SET risk_tier = 3 WHERE tool_name IN (
    -- Deletion operations
    'delete_fact', 'delete_memory', 'purge_memories',
    -- Override operations
    'request_override', 'revoke_override',
    -- System modifications
    'modify_system_config', 'reset_identity',
    -- Irreversible actions
    'execute_external_command', 'modify_database_schema',
    -- Financial/sensitive
    'execute_payment', 'modify_credentials'
);

-- Set remaining unclassified tools to Tier 1 (standard)
UPDATE jarvis_tools SET risk_tier = 1 WHERE risk_tier IS NULL;

-- Create index for fast tier lookups
CREATE INDEX IF NOT EXISTS idx_jarvis_tools_risk_tier ON jarvis_tools(risk_tier);

-- Add view for easy tier overview
CREATE OR REPLACE VIEW v_tools_by_risk_tier AS
SELECT
    t.risk_tier,
    r.name as tier_name,
    r.requirement,
    COUNT(*) as tool_count,
    STRING_AGG(t.tool_name, ', ' ORDER BY t.tool_name) as tools
FROM jarvis_tools t
LEFT JOIN tool_risk_tiers r ON t.risk_tier = r.tier
WHERE t.is_enabled = TRUE
GROUP BY t.risk_tier, r.name, r.requirement
ORDER BY t.risk_tier;

-- Comments
COMMENT ON TABLE tool_risk_tiers IS 'L0.1: Risk tier definitions for tool categorization';
COMMENT ON VIEW v_tools_by_risk_tier IS 'L0.1: Overview of tools grouped by risk tier';
