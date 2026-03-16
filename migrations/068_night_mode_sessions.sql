-- Migration 068: Night Mode Sessions
-- Session state persistence for crash recovery
-- Created: 2026-02-10

-- Session state for Night Mode execution
CREATE TABLE IF NOT EXISTS night_mode_sessions (
    id UUID PRIMARY KEY,
    night_date DATE NOT NULL,
    phase VARCHAR(20) NOT NULL DEFAULT 'idle',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    tasks_selected INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    tasks_failed INTEGER DEFAULT 0,
    total_duration_ms DECIMAL(12,2) DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for session recovery
CREATE INDEX IF NOT EXISTS idx_nm_sessions_phase ON night_mode_sessions(phase);
CREATE INDEX IF NOT EXISTS idx_nm_sessions_night_date ON night_mode_sessions(night_date);

-- Grants
GRANT ALL ON night_mode_sessions TO jarvis;

COMMENT ON TABLE night_mode_sessions IS 'Night Mode session state for crash recovery';
