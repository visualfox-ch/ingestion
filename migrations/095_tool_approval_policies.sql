-- Migration: Tool Approval Policies
-- Phase 19.6.1: Clear autonomy boundaries
--
-- Tools that modify persistent state need user confirmation
-- Tools that only read/analyze can run autonomously

-- ============================================================
-- SET REQUIRES_APPROVAL FOR STATE-MODIFYING TOOLS
-- ============================================================

-- Learning/Memory Tools - User should confirm what gets stored
UPDATE jarvis_tools SET requires_approval = true, updated_at = NOW()
WHERE name IN (
    'record_learning',
    'record_learnings_batch',
    'remember_fact'
);

-- Knowledge Base Management - User should confirm indexing
UPDATE jarvis_tools SET requires_approval = true, updated_at = NOW()
WHERE name IN (
    'manage_knowledge_sources',
    'ingest_knowledge'
);

-- Self-Modification Tools - Always require approval
UPDATE jarvis_tools SET requires_approval = true, updated_at = NOW()
WHERE name IN (
    'write_dynamic_tool',
    'promote_sandbox_tool',
    'manage_tool_registry',
    'add_decision_rule'
);

-- Identity Evolution - Require approval
UPDATE jarvis_tools SET requires_approval = true, updated_at = NOW()
WHERE name IN (
    'evolve_identity',
    'update_relationship'
);

-- ============================================================
-- TOOLS THAT STAY AUTONOMOUS (no approval needed)
-- ============================================================
-- These are read-only or low-impact:
-- - get_learnings (read only)
-- - store_context (temporary state, expires)
-- - recall_context (read only)
-- - search_* tools (read only)
-- - get_* tools (read only)
-- - send_telegram_message (communication, user sees it immediately)

-- ============================================================
-- ADD DECISION RULE FOR APPROVAL FLOW
-- ============================================================
INSERT INTO jarvis_decision_rules (
    name,
    description,
    condition_type,
    condition_value,
    action_type,
    action_value,
    enabled,
    priority,
    created_by
) VALUES (
    'require_approval_for_persistence',
    'Tools that modify persistent state need user confirmation',
    'tool_flag',
    '{"flag": "requires_approval", "value": true}',
    'require_confirmation',
    '{"message_template": "Soll ich das speichern? {tool_name}: {summary}"}',
    true,
    100,
    'system'
) ON CONFLICT DO NOTHING;

-- ============================================================
-- LOG THIS CHANGE
-- ============================================================
INSERT INTO jarvis_self_modifications (
    target_table,
    target_name,
    modification_type,
    new_value,
    reason,
    confidence,
    created_at
) VALUES (
    'jarvis_tools',
    'multiple_tools',
    'update',
    '{"requires_approval": true, "tools": ["record_learning", "record_learnings_batch", "remember_fact", "manage_knowledge_sources", "ingest_knowledge", "write_dynamic_tool", "promote_sandbox_tool", "manage_tool_registry", "add_decision_rule", "evolve_identity", "update_relationship"]}',
    'Phase 19.6.1: Clear autonomy policies - persistence tools need user confirmation',
    1.0,
    NOW()
);

-- ============================================================
-- VERIFY
-- ============================================================
-- SELECT name, requires_approval FROM jarvis_tools WHERE requires_approval = true ORDER BY name;
