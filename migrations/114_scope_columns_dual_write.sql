-- Migration 114: Scope Columns Dual-Write
-- Fuegt scope_org + scope_visibility als neue Spalten zu bestehenden Tabellen hinzu.
-- Bestehendes namespace-Feld bleibt erhalten (Dual-Write Phase).
-- namespace-Spalten werden erst in Migration 115 (Release 2) gedroppt.

-- ============ connector_state ============
ALTER TABLE connector_state
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- Backfill: Legacy-Namespace → Scope-Felder
UPDATE connector_state SET
    scope_org = CASE
        WHEN namespace = 'private'        THEN 'personal'
        WHEN namespace = 'work_projektil' THEN 'projektil'
        WHEN namespace = 'work_visualfox' THEN 'visualfox'
        WHEN namespace = 'shared'         THEN 'personal'
        ELSE 'projektil'
    END,
    scope_visibility = CASE
        WHEN namespace = 'private' THEN 'private'
        WHEN namespace = 'shared'  THEN 'shared'
        ELSE 'internal'
    END
WHERE scope_org IS NULL;

CREATE INDEX IF NOT EXISTS idx_connector_state_scope
    ON connector_state(scope_org, scope_visibility);

-- ============ ingest_event ============
ALTER TABLE ingest_event
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT,
    ADD COLUMN IF NOT EXISTS scope_domain     TEXT;

-- Backfill: Legacy-Namespace → Scope-Felder
UPDATE ingest_event SET
    scope_org = CASE
        WHEN namespace = 'private'        THEN 'personal'
        WHEN namespace = 'work_projektil' THEN 'projektil'
        WHEN namespace = 'work_visualfox' THEN 'visualfox'
        WHEN namespace = 'shared'         THEN 'personal'
        ELSE 'projektil'
    END,
    scope_visibility = CASE
        WHEN namespace = 'private' THEN 'private'
        WHEN namespace = 'shared'  THEN 'shared'
        ELSE 'internal'
    END
WHERE scope_org IS NULL;

CREATE INDEX IF NOT EXISTS idx_ingest_event_scope
    ON ingest_event(scope_org, scope_visibility);

-- ============ conversation ============
ALTER TABLE conversation
    ADD COLUMN IF NOT EXISTS scope_org        TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

-- Backfill
UPDATE conversation SET
    scope_org = CASE
        WHEN namespace = 'private'        THEN 'personal'
        WHEN namespace = 'work_projektil' THEN 'projektil'
        WHEN namespace = 'work_visualfox' THEN 'visualfox'
        WHEN namespace = 'shared'         THEN 'personal'
        ELSE 'projektil'
    END,
    scope_visibility = CASE
        WHEN namespace = 'private' THEN 'private'
        WHEN namespace = 'shared'  THEN 'shared'
        ELSE 'internal'
    END
WHERE scope_org IS NULL;

CREATE INDEX IF NOT EXISTS idx_conversation_scope
    ON conversation(scope_org, scope_visibility);

-- ============ telegram_user ============
ALTER TABLE telegram_user
    ADD COLUMN IF NOT EXISTS default_org        TEXT DEFAULT 'projektil',
    ADD COLUMN IF NOT EXISTS default_visibility TEXT DEFAULT 'internal';

-- Backfill
UPDATE telegram_user SET
    default_org = CASE
        WHEN namespace = 'private'        THEN 'personal'
        WHEN namespace = 'work_projektil' THEN 'projektil'
        WHEN namespace = 'work_visualfox' THEN 'visualfox'
        ELSE 'projektil'
    END,
    default_visibility = CASE
        WHEN namespace = 'private' THEN 'private'
        ELSE 'internal'
    END
WHERE default_org IS NULL OR default_org = 'projektil';

-- ============ Kommentare ============
COMMENT ON COLUMN connector_state.scope_org IS 'Scope-Organisation (Dual-Write). Ersetzt namespace in Release 2.';
COMMENT ON COLUMN connector_state.scope_visibility IS 'Scope-Sichtbarkeit (Dual-Write). Ersetzt namespace in Release 2.';
COMMENT ON COLUMN ingest_event.scope_org IS 'Scope-Organisation (Dual-Write). Ersetzt namespace in Release 2.';
COMMENT ON COLUMN ingest_event.scope_visibility IS 'Scope-Sichtbarkeit (Dual-Write). Ersetzt namespace in Release 2.';
COMMENT ON COLUMN ingest_event.scope_domain IS 'Fachliche Domain des Ingest-Events (linkedin, email, chat, etc.)';
