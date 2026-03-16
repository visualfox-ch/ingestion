-- Phase 17.5C: Dev Team Communication Channel
-- Creates inbox + responses tables for async AI team messaging.

CREATE TABLE IF NOT EXISTS dev_team_inbox (
    id SERIAL PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    from_agent TEXT DEFAULT 'jarvis',
    to_agent TEXT NOT NULL,
    message_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    priority TEXT DEFAULT 'medium',
    data JSONB,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS dev_team_responses (
    id SERIAL PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES dev_team_inbox(message_id),
    from_agent TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dev_team_inbox_to_agent ON dev_team_inbox(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_dev_team_inbox_priority ON dev_team_inbox(priority, created_at);
