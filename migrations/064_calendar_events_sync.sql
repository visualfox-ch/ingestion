-- Migration 064: Calendar Events Sync
-- Persistent storage for Google Calendar events
-- Enables historical queries and pattern detection

-- Calendar events table
CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(255) NOT NULL,
    account VARCHAR(50) NOT NULL,  -- 'projektil' or 'visualfox'
    calendar_id VARCHAR(255),

    -- Event details
    summary TEXT,
    description TEXT,
    location TEXT,

    -- Timing
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    all_day BOOLEAN DEFAULT FALSE,
    timezone VARCHAR(50),

    -- Status
    status VARCHAR(20) DEFAULT 'confirmed',  -- confirmed, tentative, cancelled
    visibility VARCHAR(20),  -- public, private

    -- Attendees (JSON array)
    attendees JSONB DEFAULT '[]',
    organizer VARCHAR(255),

    -- Recurrence
    recurring_event_id VARCHAR(255),
    recurrence_rule TEXT,

    -- Links
    html_link TEXT,
    hangout_link TEXT,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    etag VARCHAR(100),

    -- Unique constraint on event_id + account
    UNIQUE(event_id, account)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_calendar_events_account ON calendar_events(account);
CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_time);
CREATE INDEX IF NOT EXISTS idx_calendar_events_end ON calendar_events(end_time);
CREATE INDEX IF NOT EXISTS idx_calendar_events_status ON calendar_events(status);
CREATE INDEX IF NOT EXISTS idx_calendar_events_account_time ON calendar_events(account, start_time, end_time);

-- Sync history table
CREATE TABLE IF NOT EXISTS calendar_sync_history (
    id SERIAL PRIMARY KEY,
    account VARCHAR(50) NOT NULL,
    sync_type VARCHAR(20) NOT NULL,  -- 'full', 'incremental'
    events_synced INTEGER DEFAULT 0,
    events_added INTEGER DEFAULT 0,
    events_updated INTEGER DEFAULT 0,
    events_deleted INTEGER DEFAULT 0,
    sync_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sync_end TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'running',  -- running, completed, failed
    error_message TEXT,
    date_range_start TIMESTAMP WITH TIME ZONE,
    date_range_end TIMESTAMP WITH TIME ZONE
);

-- Index for sync history queries
CREATE INDEX IF NOT EXISTS idx_calendar_sync_account ON calendar_sync_history(account);
CREATE INDEX IF NOT EXISTS idx_calendar_sync_status ON calendar_sync_history(status);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_calendar_events_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for auto-updating timestamp
DROP TRIGGER IF EXISTS calendar_events_update_timestamp ON calendar_events;
CREATE TRIGGER calendar_events_update_timestamp
    BEFORE UPDATE ON calendar_events
    FOR EACH ROW
    EXECUTE FUNCTION update_calendar_events_timestamp();

-- Comment on tables
COMMENT ON TABLE calendar_events IS 'Persistent storage for Google Calendar events - enables historical queries';
COMMENT ON TABLE calendar_sync_history IS 'Tracks calendar sync operations for monitoring';
