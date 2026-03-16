-- Migration: Google Resources Registry
-- Allows Jarvis to store references to Google Sheets, Docs, Folders, etc.
-- These can then be accessed by name instead of remembering IDs

CREATE TABLE IF NOT EXISTS google_resources (
    id SERIAL PRIMARY KEY,

    -- Resource identification
    resource_type VARCHAR(20) NOT NULL,  -- 'sheet', 'doc', 'folder', 'presentation', 'chat_space'
    resource_id VARCHAR(100) NOT NULL,   -- Google's resource ID

    -- Human-readable info
    name VARCHAR(255) NOT NULL,          -- e.g., "EONARIUM Locations"
    description TEXT,                     -- What this resource contains/is for

    -- Access configuration
    account VARCHAR(50) DEFAULT 'projektil',  -- Which Google account
    permissions VARCHAR(20) DEFAULT 'read',   -- 'read', 'write', 'admin'

    -- Resource-specific metadata
    metadata JSONB DEFAULT '{}',
    -- For sheets: {"sheet_name": "Sheet1", "range": "A:Z"}
    -- For folders: {"parent_folder": "...", "sync_enabled": true}
    -- For chat_space: {"space_type": "ROOM", "display_name": "..."}

    -- Tracking
    last_accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system',

    -- Constraints
    UNIQUE(resource_type, resource_id),
    UNIQUE(resource_type, name)  -- Names must be unique per type
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_google_resources_type ON google_resources(resource_type);
CREATE INDEX IF NOT EXISTS idx_google_resources_name ON google_resources(name);
CREATE INDEX IF NOT EXISTS idx_google_resources_account ON google_resources(account);

-- Insert initial resources
INSERT INTO google_resources (resource_type, resource_id, name, description, account, permissions, metadata)
VALUES
    ('folder', '0AAv4qT_wyvtkUk9PVA', 'EONARIUM Main', 'EONARIUM Haupt-Ordner mit allen Projekt-Dokumenten', 'projektil', 'read', '{"project": "eonarium"}'),
    ('folder', '14EfPAOHI6GsZvmPpOaAeKyciGfoi6b4z', 'EONARIUM Locations', 'EONARIUM Standort-Dokumentation', 'projektil', 'read', '{"project": "eonarium", "subfolder": "locations"}')
ON CONFLICT (resource_type, resource_id) DO NOTHING;

-- Function to update last_accessed tracking
CREATE OR REPLACE FUNCTION update_google_resource_access()
RETURNS TRIGGER AS $$
BEGIN
    NEW.access_count := OLD.access_count + 1;
    NEW.last_accessed_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE google_resources IS 'Registry of Google resources (Sheets, Docs, Folders) that Jarvis can access';
COMMENT ON COLUMN google_resources.resource_type IS 'Type: sheet, doc, folder, presentation, chat_space';
COMMENT ON COLUMN google_resources.resource_id IS 'Google resource ID from the URL';
COMMENT ON COLUMN google_resources.metadata IS 'Type-specific config like sheet_name, range, sync settings';
