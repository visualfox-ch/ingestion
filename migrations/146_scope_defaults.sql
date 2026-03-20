-- Migration 113: Scope Defaults per Channel
-- Bestimmt den Default-Scope pro Kanal/Source.
-- Ersetzt die hardcodierten Defaults in AgentRequest, agent.py und coaching_domains.py.

CREATE TABLE IF NOT EXISTS scope_defaults (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Lookup-Key: Wofuer gilt dieser Default?
    channel             TEXT NOT NULL,  -- "telegram" | "api" | "n8n" | "whatsapp" | "gchat" | "gmail"
    source_type         TEXT,           -- Optional: Einschraenkung auf bestimmten Source-Typ
    user_id             TEXT,           -- Optional: Einschraenkung auf bestimmten User

    -- Default-Scope (referenziert scope_policy via org + visibility)
    default_org         TEXT NOT NULL DEFAULT 'projektil',
    default_visibility  TEXT NOT NULL DEFAULT 'internal',
    default_owner       TEXT NOT NULL DEFAULT 'michael_bohl',

    -- Verwaltung
    description         TEXT,
    active              BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scope_defaults_channel ON scope_defaults(channel);
CREATE INDEX IF NOT EXISTS idx_scope_defaults_active ON scope_defaults(active);
-- Unique index using COALESCE (expressions not allowed in UNIQUE constraint, use index instead)
CREATE UNIQUE INDEX IF NOT EXISTS idx_scope_defaults_unique
    ON scope_defaults(channel, COALESCE(source_type, ''), COALESCE(user_id, ''));

COMMENT ON TABLE scope_defaults IS 'Default-Scope pro Kanal. Ersetzt hardcodierte Defaults in API-Requests.';
COMMENT ON COLUMN scope_defaults.channel IS 'Kommunikationskanal: telegram | api | n8n | whatsapp | gchat | gmail';

-- Initial-Daten: Default-Scope fuer alle aktiven Kanaele
INSERT INTO scope_defaults (channel, default_org, default_visibility, default_owner, description) VALUES
    ('telegram',  'projektil', 'internal', 'michael_bohl', 'Telegram-Bot Default'),
    ('api',       'projektil', 'internal', 'michael_bohl', 'REST API Default'),
    ('n8n',       'projektil', 'internal', 'michael_bohl', 'n8n Workflow Default'),
    ('whatsapp',  'projektil', 'internal', 'michael_bohl', 'WhatsApp Ingest Default'),
    ('gchat',     'projektil', 'internal', 'michael_bohl', 'Google Chat Ingest Default'),
    ('gmail',     'projektil', 'internal', 'michael_bohl', 'Gmail Ingest Default')
ON CONFLICT DO NOTHING;
