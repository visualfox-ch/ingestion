-- Migration 115: scope_alias_resolution
-- Erstellt eine deterministische Mapping-Tabelle: legacy_namespace → (org, visibility, domain).
-- Jeder bekannte Produktionswert ist explizit eingetragen.
-- Felder mit review_required=TRUE muessen vor dem Backfill manuell geprueft werden.
-- Kein ELSE-Default: unbekannte Werte werden nicht still umgebogen.
--
-- Produktions-Snapshot (17.03.2026):
--   work_projektil: 1788 | private: 695 | ingestion: 185 | default: 156 | test: 34
--   shared: 17 | telegram_work_projektil: 16 | telegram_private: 10
--   telegram_1465947014: 6 | jarvis_system: 6 | ops: 5 | NULL: 4 | general: 4
--   system: 3 | self_improvement: 2 | public: 2 | demo: 1 | work_visualfox: 1
--   comms: 1 | jarvis_dev: 1 | jarvis: 1 | prometheus_test: 1

CREATE TABLE IF NOT EXISTS scope_alias_resolution (
    id                 SERIAL        PRIMARY KEY,
    legacy_namespace   TEXT          UNIQUE,              -- NULL row = NULL-namespace records
    target_org         TEXT          NOT NULL,
    target_visibility  TEXT          NOT NULL,
    target_domain      TEXT,                              -- NULL = no domain
    confidence         TEXT          NOT NULL DEFAULT 'high',  -- 'high' | 'medium'
    review_required    BOOLEAN       NOT NULL DEFAULT FALSE,
    review_note        TEXT,
    production_rows    INT,                               -- snapshot count at migration time
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE scope_alias_resolution IS
    'Deterministische Alias-Auflösung: legacy_namespace → Scope-Felder. '
    'review_required=TRUE bedeutet: Backfill für diese Zeile ist gesperrt bis Review erfolgt.';

-- ============================================================
-- HIGH CONFIDENCE: Canonical + clear semantic mappings
-- ============================================================

-- 4 canonical values (already in _NAMESPACE_TO_SCOPE in models.py)
INSERT INTO scope_alias_resolution
    (legacy_namespace, target_org, target_visibility, target_domain, confidence, review_required, review_note, production_rows)
VALUES
    ('work_projektil',          'projektil', 'internal', NULL,           'high', FALSE, 'Canonical',                                   1788),
    ('private',                 'personal',  'private',  NULL,           'high', FALSE, 'Canonical',                                    695),
    ('shared',                  'personal',  'shared',   NULL,           'high', FALSE, 'Canonical',                                     17),
    ('work_visualfox',          'visualfox', 'internal', NULL,           'high', FALSE, 'Canonical',                                      1),

    -- Ingestion pipeline: always projektil-internal, domain=ingestion
    ('ingestion',               'projektil', 'internal', 'ingestion',    'high', FALSE, 'Ingestion-Pipeline-Daten',                     185),

    -- Telegram channels with clear org/visibility semantics
    ('telegram_work_projektil', 'projektil', 'internal', 'telegram',     'high', FALSE, 'Telegram Projektil-Kanal',                      16),
    ('telegram_private',        'personal',  'private',  'telegram',     'high', FALSE, 'Telegram privater Kanal',                       10),

    -- Test/Dev/Demo/Monitoring data
    ('test',                    'projektil', 'internal', 'test',         'high', FALSE, 'Testdaten',                                     34),
    ('demo',                    'projektil', 'internal', 'demo',         'high', FALSE, 'Demo/Sample-Daten',                              1),
    ('prometheus_test',         'projektil', 'internal', 'monitoring',   'high', FALSE, 'Prometheus-Testmetriken',                        1),
    ('jarvis_dev',              'projektil', 'internal', 'dev',          'high', FALSE, 'Jarvis-Entwicklungsnamespace',                   1),

    -- Public data
    ('public',                  'projektil', 'public',   NULL,           'high', FALSE, 'Öffentliche Daten',                              2)
ON CONFLICT (legacy_namespace) DO NOTHING;

-- ============================================================
-- MEDIUM CONFIDENCE: Plausible mappings, human review recommended
-- ============================================================

INSERT INTO scope_alias_resolution
    (legacy_namespace, target_org, target_visibility, target_domain, confidence, review_required, review_note, production_rows)
VALUES
    ('jarvis',          'projektil', 'internal', NULL,      'medium', FALSE,
        'Generische Jarvis-Daten – plausibel projektil/internal',                1),
    ('ops',             'projektil', 'internal', 'ops',     'medium', FALSE,
        'Operations-Daten – plausibel projektil/internal',                       5),
    ('system',          'projektil', 'internal', 'system',  'medium', FALSE,
        'Systemdaten – plausibel projektil/internal',                            3),
    ('jarvis_system',   'projektil', 'internal', 'system',  'medium', FALSE,
        'Jarvis-Systemdaten – plausibel projektil/internal',                     6)
ON CONFLICT (legacy_namespace) DO NOTHING;

-- ============================================================
-- REVIEW REQUIRED: Ambiguous values – Backfill gesperrt bis Review
-- ============================================================

INSERT INTO scope_alias_resolution
    (legacy_namespace, target_org, target_visibility, target_domain, confidence, review_required, review_note, production_rows)
VALUES
    ('default',             'projektil', 'internal', NULL,     'medium', TRUE,
        'REVIEW: 156 Zeilen mit Generic-Fallback. Herkunft prüfen – könnte work oder personal sein.',
        156),
    ('general',             'projektil', 'internal', NULL,     'medium', TRUE,
        'REVIEW: Semantisch unklar – Work oder Personal?',
        4),
    ('telegram_1465947014', 'personal',  'private',  'telegram','medium', TRUE,
        'REVIEW: Telegram-User-ID – wem gehört diese ID? Wahrscheinlich Michael, aber Bestätigung nötig.',
        6),
    ('self_improvement',    'personal',  'private',  NULL,     'medium', TRUE,
        'REVIEW: Persönliche Weiterentwicklung? Oder Jarvis-intern? Scope uncertain.',
        2),
    ('comms',               'projektil', 'internal', 'comms',  'medium', TRUE,
        'REVIEW: Communications-Namespace – Work oder persönlich?',
        1)
ON CONFLICT (legacy_namespace) DO NOTHING;

-- NULL-namespace records: separate row with legacy_namespace IS NULL is not representable
-- as a UNIQUE key directly. We use empty string '' as sentinel.
INSERT INTO scope_alias_resolution
    (legacy_namespace, target_org, target_visibility, target_domain, confidence, review_required, review_note, production_rows)
VALUES
    ('',                    'projektil', 'internal', NULL,     'medium', TRUE,
        'REVIEW: NULL-namespace Zeilen (4 Stück). Herkunft prüfen vor Backfill.',
        4)
ON CONFLICT (legacy_namespace) DO NOTHING;

-- ============================================================
-- Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_scope_alias_review
    ON scope_alias_resolution(review_required)
    WHERE review_required = TRUE;

CREATE INDEX IF NOT EXISTS idx_scope_alias_namespace
    ON scope_alias_resolution(legacy_namespace);
