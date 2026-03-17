-- Migration 116: Scope-Spalten für verbleibende namespace-tragende Tabellen
-- Migration 114 hat bereits: connector_state, ingest_event, conversation, telegram_user
-- Diese Migration ergänzt alle restlichen 14 Tabellen mit namespace-Spalten.
--
-- Wichtig: KEIN Backfill hier. Der Backfill erfolgt separat über scripts/scope_backfill.py
-- nachdem scope_alias_resolution manuell reviewed wurde (Migration 115).
-- Dual-Write gilt ab diesem Punkt: Der Applikations-Code schreibt scope_org/visibility
-- sobald die Schreib-Cutover-Phase aktiv ist.

-- ============ decision_logs ============
ALTER TABLE decision_logs
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

CREATE INDEX IF NOT EXISTS idx_decision_logs_scope
    ON decision_logs(scope_org, scope_visibility);

COMMENT ON COLUMN decision_logs.scope_org IS 'Scope-Org (Phase 2 Dual-Write). namespace bleibt als Provenance.';
COMMENT ON COLUMN decision_logs.scope_visibility IS 'Scope-Visibility (Phase 2 Dual-Write).';

-- ============ learned_facts ============
ALTER TABLE learned_facts
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

CREATE INDEX IF NOT EXISTS idx_learned_facts_scope
    ON learned_facts(scope_org, scope_visibility);

COMMENT ON COLUMN learned_facts.scope_org IS 'Scope-Org (Phase 2 Dual-Write).';
COMMENT ON COLUMN learned_facts.scope_visibility IS 'Scope-Visibility (Phase 2 Dual-Write).';

-- ============ memory_facts_layered ============
ALTER TABLE memory_facts_layered
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

CREATE INDEX IF NOT EXISTS idx_memory_facts_layered_scope
    ON memory_facts_layered(scope_org, scope_visibility);

COMMENT ON COLUMN memory_facts_layered.scope_org IS 'Scope-Org (Phase 2 Dual-Write).';
COMMENT ON COLUMN memory_facts_layered.scope_visibility IS 'Scope-Visibility (Phase 2 Dual-Write).';

-- ============ upload_queue ============
ALTER TABLE upload_queue
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT,
    ADD COLUMN IF NOT EXISTS scope_domain     TEXT;

CREATE INDEX IF NOT EXISTS idx_upload_queue_scope
    ON upload_queue(scope_org, scope_visibility);

COMMENT ON COLUMN upload_queue.scope_org IS 'Scope-Org (Phase 2 Dual-Write).';
COMMENT ON COLUMN upload_queue.scope_visibility IS 'Scope-Visibility (Phase 2 Dual-Write).';
COMMENT ON COLUMN upload_queue.scope_domain IS 'Fachliche Domain des Uploads (linkedin, email, chat, etc.)';

-- ============ interaction_quality ============
ALTER TABLE interaction_quality
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

CREATE INDEX IF NOT EXISTS idx_interaction_quality_scope
    ON interaction_quality(scope_org, scope_visibility);

-- ============ knowledge_item ============
ALTER TABLE knowledge_item
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT,
    ADD COLUMN IF NOT EXISTS scope_domain     TEXT;

CREATE INDEX IF NOT EXISTS idx_knowledge_item_scope
    ON knowledge_item(scope_org, scope_visibility);

COMMENT ON COLUMN knowledge_item.scope_domain IS 'Fachliche Domain des Knowledge-Items.';

-- ============ chat_sync_state ============
ALTER TABLE chat_sync_state
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ entity_mentions ============
ALTER TABLE entity_mentions
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

CREATE INDEX IF NOT EXISTS idx_entity_mentions_scope
    ON entity_mentions(scope_org, scope_visibility);

-- ============ pattern_history ============
ALTER TABLE pattern_history
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ prompt_fragment ============
ALTER TABLE prompt_fragment
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ conversation_context ============
-- (context linked to conversation, inherits scope from conversation row)
ALTER TABLE conversation_context
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ person_channel_preference ============
ALTER TABLE person_channel_preference
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ person_relationship ============
ALTER TABLE person_relationship
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ hygiene_baselines ============
ALTER TABLE hygiene_baselines
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- ============ knowledge_evidence_link ============
-- knowledge_evidence_link may inherit scope from the linked knowledge_item
ALTER TABLE knowledge_evidence_link
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;
