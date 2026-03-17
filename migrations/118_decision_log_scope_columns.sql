-- Migration 118: Add scope columns to decision_log (runtime-active table)
-- NOTE: Both decision_log and decision_logs exist in production.
-- Runtime writers currently target decision_log, so it must also support dual-write.

ALTER TABLE decision_log
    ADD COLUMN IF NOT EXISTS scope_org TEXT,
    ADD COLUMN IF NOT EXISTS scope_visibility TEXT;

CREATE INDEX IF NOT EXISTS idx_decision_log_scope
    ON decision_log(scope_org, scope_visibility);

COMMENT ON COLUMN decision_log.scope_org IS 'Scope-Org (Dual-Write). Mirrors legacy namespace semantics.';
COMMENT ON COLUMN decision_log.scope_visibility IS 'Scope-Visibility (Dual-Write). Mirrors legacy namespace semantics.';
