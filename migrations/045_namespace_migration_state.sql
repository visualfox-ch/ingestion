CREATE TABLE IF NOT EXISTS namespace_migration_state (
    namespace TEXT PRIMARY KEY,
    labels_applied BOOLEAN DEFAULT FALSE,
    labels_applied_at TIMESTAMP,
    reindex_allowed BOOLEAN DEFAULT FALSE,
    reindex_allowed_at TIMESTAMP,
    notes TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_namespace_migration_state_updated
ON namespace_migration_state(updated_at DESC);
