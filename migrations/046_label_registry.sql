CREATE TABLE IF NOT EXISTS label_registry (
    key TEXT PRIMARY KEY,
    description TEXT,
    allowed_values JSONB,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_label_registry_status
    ON label_registry(status);
