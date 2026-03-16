-- Migration 028: Sessions table for Phase 19.5B

-- Create sessions table
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id UUID UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    
    -- Lifecycle
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    
    -- Data
    conversation_history JSONB DEFAULT '[]',
    facette_weights JSONB DEFAULT '{}',
    learned_facts_ids INTEGER[] DEFAULT '{}',
    user_preferences JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    
    -- Indexing
    created_idx TIMESTAMP,
    updated_idx TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user_created ON sessions(user_id, created_at DESC);

-- Trigger to update last_activity
CREATE OR REPLACE FUNCTION update_session_activity()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_activity = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_session_activity
BEFORE UPDATE ON sessions
FOR EACH ROW
EXECUTE FUNCTION update_session_activity();

-- Comment
COMMENT ON TABLE sessions IS 'Persistent session storage for Phase 19.5B - State & Persistence';
COMMENT ON COLUMN sessions.session_id IS 'UUID session identifier, unique across system';
COMMENT ON COLUMN sessions.user_id IS 'Associated user ID';
COMMENT ON COLUMN sessions.conversation_history IS 'JSONB array of {role, content, timestamp} messages';
COMMENT ON COLUMN sessions.facette_weights IS 'JSONB of personality trait weights for restoration';
COMMENT ON COLUMN sessions.learned_facts_ids IS 'Array of IDs referencing learned_facts table';
COMMENT ON COLUMN sessions.expires_at IS 'Session expiration timestamp (NULL = no expiry)';
