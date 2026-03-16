-- Migration: Google API Cache
-- Hybrid caching: Redis for fast access, PostgreSQL for persistence and history

-- Main cache table for Google API responses
CREATE TABLE IF NOT EXISTS google_api_cache (
    id SERIAL PRIMARY KEY,

    -- Cache key components
    service VARCHAR(20) NOT NULL,        -- 'calendar', 'gmail', 'drive', 'sheets', 'docs', 'chat'
    account VARCHAR(50) NOT NULL,         -- 'projektil', 'visualfox'
    cache_key VARCHAR(255) NOT NULL,      -- Hash of params or specific resource ID

    -- Cached data
    data JSONB NOT NULL,                  -- The actual API response
    item_count INTEGER DEFAULT 0,         -- Number of items in response

    -- TTL management
    ttl_seconds INTEGER NOT NULL,         -- How long this cache is valid
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,

    -- Access tracking
    hit_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMP,

    -- Freshness tracking
    api_fetched_at TIMESTAMP NOT NULL,    -- When data was fetched from Google
    data_hash VARCHAR(64),                -- MD5 hash to detect changes

    UNIQUE(service, account, cache_key)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_google_cache_service ON google_api_cache(service);
CREATE INDEX IF NOT EXISTS idx_google_cache_expires ON google_api_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_google_cache_lookup ON google_api_cache(service, account, cache_key);

-- Historical data table (for analytics and longer-term storage)
CREATE TABLE IF NOT EXISTS google_api_cache_history (
    id SERIAL PRIMARY KEY,

    service VARCHAR(20) NOT NULL,
    account VARCHAR(50) NOT NULL,
    cache_key VARCHAR(255) NOT NULL,

    -- Snapshot of data at this point
    data JSONB NOT NULL,
    item_count INTEGER DEFAULT 0,
    data_hash VARCHAR(64),

    -- Timing
    fetched_at TIMESTAMP NOT NULL,
    archived_at TIMESTAMP DEFAULT NOW(),

    -- Why was this archived?
    archive_reason VARCHAR(50) DEFAULT 'expiry'  -- 'expiry', 'update', 'manual'
);

-- Index for history queries
CREATE INDEX IF NOT EXISTS idx_google_cache_history_lookup
ON google_api_cache_history(service, account, fetched_at DESC);

-- Cache configuration table
CREATE TABLE IF NOT EXISTS google_cache_config (
    service VARCHAR(20) PRIMARY KEY,

    -- TTL settings (in seconds)
    default_ttl INTEGER NOT NULL,
    min_ttl INTEGER DEFAULT 60,
    max_ttl INTEGER DEFAULT 3600,

    -- Behavior
    cache_enabled BOOLEAN DEFAULT TRUE,
    archive_on_expiry BOOLEAN DEFAULT TRUE,
    max_history_days INTEGER DEFAULT 30,

    -- Stats
    total_hits INTEGER DEFAULT 0,
    total_misses INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW()
);

-- Insert default configurations
INSERT INTO google_cache_config (service, default_ttl, min_ttl, max_ttl, archive_on_expiry, max_history_days)
VALUES
    ('calendar', 600, 60, 1800, TRUE, 30),      -- 10 min default, max 30 min
    ('gmail', 300, 60, 900, TRUE, 7),           -- 5 min default, max 15 min
    ('drive', 1800, 300, 3600, TRUE, 30),       -- 30 min default, max 1 hour
    ('sheets', 900, 120, 1800, TRUE, 14),       -- 15 min default, max 30 min
    ('docs', 1800, 300, 3600, FALSE, 7),        -- 30 min default, no history
    ('chat', 180, 30, 600, TRUE, 3)             -- 3 min default, max 10 min
ON CONFLICT (service) DO NOTHING;

-- Function to update hit count and last accessed
CREATE OR REPLACE FUNCTION update_cache_hit()
RETURNS TRIGGER AS $$
BEGIN
    NEW.hit_count := OLD.hit_count + 1;
    NEW.last_accessed_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to archive expired cache entries
CREATE OR REPLACE FUNCTION archive_expired_cache()
RETURNS INTEGER AS $$
DECLARE
    archived_count INTEGER;
BEGIN
    -- Move expired entries to history (if configured)
    INSERT INTO google_api_cache_history (service, account, cache_key, data, item_count, data_hash, fetched_at, archive_reason)
    SELECT c.service, c.account, c.cache_key, c.data, c.item_count, c.data_hash, c.api_fetched_at, 'expiry'
    FROM google_api_cache c
    JOIN google_cache_config cfg ON c.service = cfg.service
    WHERE c.expires_at < NOW() AND cfg.archive_on_expiry = TRUE;

    GET DIAGNOSTICS archived_count = ROW_COUNT;

    -- Delete expired entries
    DELETE FROM google_api_cache WHERE expires_at < NOW();

    RETURN archived_count;
END;
$$ LANGUAGE plpgsql;

-- Function to clean old history entries
CREATE OR REPLACE FUNCTION cleanup_cache_history()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM google_api_cache_history h
    USING google_cache_config cfg
    WHERE h.service = cfg.service
    AND h.archived_at < NOW() - (cfg.max_history_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE google_api_cache IS 'Active cache for Google API responses';
COMMENT ON TABLE google_api_cache_history IS 'Historical snapshots of cached data';
COMMENT ON TABLE google_cache_config IS 'Per-service cache configuration';
COMMENT ON COLUMN google_api_cache.cache_key IS 'Unique key for this cache entry (hash of params)';
COMMENT ON COLUMN google_api_cache.data_hash IS 'MD5 of data to detect changes without comparing full JSON';
