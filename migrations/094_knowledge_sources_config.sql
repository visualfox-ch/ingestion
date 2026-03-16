-- Migration 094: Knowledge Sources Configuration
-- DB-gesteuerte Konfiguration für Knowledge Base Ingestion
-- Ersetzt hardcoded LINKEDIN_DOCS_CONFIG / VISUALFOX_DOCS_CONFIG

-- Haupt-Tabelle für Knowledge Source Konfiguration
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identifikation
    domain TEXT NOT NULL,           -- z.B. "linkedin", "visualfox", "pixera"
    subdomain TEXT,                 -- z.B. "strategy", "portfolio", "brand"

    -- Datei-Konfiguration
    file_path TEXT NOT NULL,        -- Pfad im Container: /brain/system/data/...
    title TEXT NOT NULL,            -- Anzeigename für Dokument

    -- Versionierung
    version TEXT NOT NULL DEFAULT '1.0',

    -- Qdrant Collection (auto-generiert wenn NULL)
    collection_name TEXT,           -- NULL = auto: "jarvis_{domain}"

    -- Metadaten für Chunks
    owner TEXT DEFAULT 'michael_bohl',
    channel TEXT,                   -- z.B. "linkedin", "brand", "technical"
    language TEXT DEFAULT 'de',
    quality TEXT DEFAULT 'high',

    -- Status
    active BOOLEAN DEFAULT true,
    auto_reingest BOOLEAN DEFAULT false,  -- Bei Datei-Änderung automatisch neu ingesten

    -- Tracking
    last_ingested_at TIMESTAMP WITH TIME ZONE,
    last_chunk_count INTEGER,
    last_error TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

    -- Unique: Ein Pfad pro Domain
    CONSTRAINT unique_domain_path UNIQUE (domain, file_path)
);

-- Indizes
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_domain ON knowledge_sources(domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_active ON knowledge_sources(active);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_collection ON knowledge_sources(collection_name);

-- Kommentare
COMMENT ON TABLE knowledge_sources IS 'DB-gesteuerte Konfiguration für Knowledge Base Ingestion. Ersetzt hardcoded Config-Listen.';
COMMENT ON COLUMN knowledge_sources.collection_name IS 'Qdrant Collection. NULL = auto-generiert als jarvis_{domain}';
COMMENT ON COLUMN knowledge_sources.auto_reingest IS 'Wenn true, wird bei Datei-Änderung automatisch neu ingestet';

-- Initial-Daten: Migration der bestehenden hardcoded Config
INSERT INTO knowledge_sources (domain, subdomain, file_path, title, version, channel, collection_name) VALUES
    -- LinkedIn
    ('linkedin', 'strategy', '/brain/system/data/linkedin/strategie/LinkedIn-Strategie-Micha-Bohl.md', 'LinkedIn-Strategie Michael Bohl 2026', '2026-03-14-v2', 'linkedin', 'jarvis_linkedin'),
    ('linkedin', 'portfolio', '/brain/system/data/linkedin/content-plan/Portfolio-Aufbauplan-Micha-Bohl.md', 'Portfolio-Aufbauplan Michael Bohl 2026', '2026-03-14-v2', 'linkedin', 'jarvis_linkedin'),
    ('linkedin', 'overview', '/brain/system/data/linkedin/LinkedIn-Strategie-Overview-2026.md', 'LinkedIn-Strategie Overview 2026', '2026-03-14', 'linkedin', 'jarvis_linkedin'),
    ('linkedin', 'assets', '/brain/system/data/linkedin/content-plan/Sora-Prompt-LinkedIn-Banner-Micha.md', 'Sora Prompt LinkedIn Banner', '2026-03-14', 'linkedin', 'jarvis_linkedin'),
    -- visualfox
    ('visualfox', 'brand', '/brain/system/data/visualfox/Brand-System-visualfox-2026.md', 'visualfox 2.0 Brand System Overview', '2026-03-14', 'brand', 'jarvis_visualfox')
ON CONFLICT (domain, file_path) DO NOTHING;
