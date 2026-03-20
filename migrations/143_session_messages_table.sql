-- Migration 070: Session Messages Table for Auto-Persist
-- Phase 19.1: Memory Persistence Fix
-- Enables automatic message tracking without explicit tool calls

-- Note: This runs against jarvis_state.db (SQLite), not PostgreSQL
-- The migration runner should detect .sqlite suffix or be run manually

-- For SQLite execution, run:
-- sqlite3 /brain/system/state/jarvis_state.db < this_file.sql

CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id INTEGER,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_index INTEGER,
    tool_calls TEXT,  -- JSON array of tool names used
    token_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_user ON session_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_timestamp ON session_messages(timestamp DESC);

-- Cleanup trigger: Auto-delete messages older than 30 days
CREATE TRIGGER IF NOT EXISTS cleanup_old_messages
AFTER INSERT ON session_messages
BEGIN
    DELETE FROM session_messages
    WHERE created_at < datetime('now', '-30 days');
END;
