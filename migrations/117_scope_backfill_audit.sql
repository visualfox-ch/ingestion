-- Migration 117: scope_backfill_audit
-- Audit-Tabelle für den Scope-Backfill.
-- Jede backgefüllte Zeile wird hier mit Herkunft, aufgelöstem Scope und
-- review_required-Flag dokumentiert. Zeilen mit review_required=TRUE
-- müssen nach dem Backfill manuell geprüft werden.
--
-- Der Backfill selbst läuft über scripts/scope_backfill.py (nie direkt als Migration,
-- damit er wiederholbar, auditierbar und unterbrechbar ist).

CREATE TABLE IF NOT EXISTS scope_backfill_audit (
    id                 BIGSERIAL     PRIMARY KEY,
    backfill_run_id    TEXT          NOT NULL,         -- UUID pro Backfill-Lauf
    table_name         TEXT          NOT NULL,
    record_id          TEXT          NOT NULL,         -- Primärschlüssel als TEXT
    legacy_namespace   TEXT,                           -- Originaler Wert (NULL-safe)
    resolved_org       TEXT          NOT NULL,
    resolved_visibility TEXT         NOT NULL,
    resolved_domain    TEXT,
    confidence         TEXT          NOT NULL,         -- 'high' | 'medium'
    review_required    BOOLEAN       NOT NULL DEFAULT FALSE,
    review_note        TEXT,
    reviewed           BOOLEAN       NOT NULL DEFAULT FALSE,
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE scope_backfill_audit IS
    'Audit-Log für scope_backfill.py. Zeilen mit review_required=TRUE sind Backfill-Kandidaten '
    'die manuell bestätigt werden müssen (ambiguous namespace values).';

-- Schneller Zugriff auf Review-Queue
CREATE INDEX IF NOT EXISTS idx_scope_backfill_review
    ON scope_backfill_audit(review_required, reviewed)
    WHERE review_required = TRUE;

-- Zugriff per Tabelle
CREATE INDEX IF NOT EXISTS idx_scope_backfill_table_run
    ON scope_backfill_audit(table_name, backfill_run_id);

-- Deduplizierung: verhindert Doppel-Einträge beim Retry
CREATE UNIQUE INDEX IF NOT EXISTS idx_scope_backfill_dedup
    ON scope_backfill_audit(table_name, record_id, backfill_run_id);
