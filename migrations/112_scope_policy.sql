-- Migration 112: Scope Policy
-- Ersetzt den hardcodierten NAMESPACES-Dict in domain_separation.py durch eine DB-Tabelle.
-- Scope = org + visibility (statt magischem String wie "work_projektil")

CREATE TABLE IF NOT EXISTS scope_policy (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scope-Komponenten (bilden zusammen den eindeutigen Scope)
    org                  TEXT NOT NULL,   -- "projektil" | "visualfox" | "personal"
    visibility           TEXT NOT NULL,   -- "private" | "internal" | "shared" | "public"

    -- Zugriffsregeln
    llm_allowed          BOOLEAN NOT NULL DEFAULT true,
    cross_access_allowed BOOLEAN NOT NULL DEFAULT false,

    -- Qdrant Collections (JSON-Array)
    qdrant_collections   JSONB NOT NULL DEFAULT '[]',

    -- Verwaltung
    description          TEXT,
    active               BOOLEAN NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT scope_policy_unique UNIQUE (org, visibility)
);

CREATE INDEX IF NOT EXISTS idx_scope_policy_org ON scope_policy(org);
CREATE INDEX IF NOT EXISTS idx_scope_policy_active ON scope_policy(active);

COMMENT ON TABLE scope_policy IS 'DB-gesteuerte Scope-Policy. Ersetzt NAMESPACES-Dict in domain_separation.py.';
COMMENT ON COLUMN scope_policy.org IS 'Organisation/Kontext: projektil | visualfox | personal';
COMMENT ON COLUMN scope_policy.visibility IS 'Sichtbarkeitsstufe: private | internal | shared | public';
COMMENT ON COLUMN scope_policy.qdrant_collections IS 'JSON-Array der erlaubten Qdrant Collections fuer diesen Scope';

-- Initial-Daten: 1:1 Mapping der heutigen NAMESPACES:
-- "private"        → personal/private
-- "work_projektil" → projektil/internal
-- "work_visualfox" → visualfox/internal
-- "shared"         → personal/shared
INSERT INTO scope_policy (org, visibility, llm_allowed, cross_access_allowed, qdrant_collections, description) VALUES
    ('personal',  'private',  false, false, '["jarvis_private", "private_comms"]', 'Persoenliche private Daten'),
    ('projektil', 'internal', true,  false, '["jarvis_work", "work_comms"]',        'Projektil Arbeitsdaten'),
    ('visualfox', 'internal', true,  false, '["jarvis_work", "work_comms"]',        'Visualfox Arbeitsdaten'),
    ('personal',  'shared',   true,  true,  '["jarvis_shared"]',                   'Geteilte domaenuebergreifende Daten')
ON CONFLICT (org, visibility) DO NOTHING;
