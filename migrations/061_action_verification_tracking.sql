-- Migration 061: Action Verification Tracking
-- Created: 2026-02-08
-- Purpose: Track verification results for external API actions
--
-- This table stores verification attempts and results for all external
-- write operations (Calendar, Gmail, Reclaim, n8n Workflows, Asana).

-- Action verification records
CREATE TABLE IF NOT EXISTS action_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Action identification
    action_id UUID,                           -- Link to audit log if available
    action_type VARCHAR(50) NOT NULL,         -- calendar_create, email_send, etc.
    external_id VARCHAR(255) NOT NULL,        -- Event ID, Task ID, Workflow ID, etc.

    -- Verification result
    status VARCHAR(20) NOT NULL,              -- verified, failed, timeout, skipped, error
    attempts INTEGER DEFAULT 1,
    reason TEXT,                              -- Failure reason if not verified

    -- State comparison
    expected_state JSONB,                     -- What we expected (optional)
    actual_state JSONB,                       -- What we found (optional)

    -- Timing
    action_executed_at TIMESTAMPTZ,           -- When the action was executed
    verified_at TIMESTAMPTZ DEFAULT NOW(),    -- When verification completed
    duration_ms FLOAT,                        -- How long verification took

    -- Metadata
    account VARCHAR(50),                      -- Account used (projektil, visualfox, etc.)
    user_id UUID,                             -- User who triggered the action
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_action_verifications_action_type
    ON action_verifications(action_type);

CREATE INDEX IF NOT EXISTS idx_action_verifications_status
    ON action_verifications(status);

CREATE INDEX IF NOT EXISTS idx_action_verifications_external_id
    ON action_verifications(external_id);

CREATE INDEX IF NOT EXISTS idx_action_verifications_verified_at
    ON action_verifications(verified_at);

CREATE INDEX IF NOT EXISTS idx_action_verifications_action_id
    ON action_verifications(action_id);

-- Verification summary view for monitoring
CREATE OR REPLACE VIEW action_verification_summary AS
SELECT
    action_type,
    status,
    COUNT(*) as count,
    AVG(duration_ms) as avg_duration_ms,
    AVG(attempts) as avg_attempts,
    MAX(verified_at) as last_verification
FROM action_verifications
WHERE verified_at > NOW() - INTERVAL '7 days'
GROUP BY action_type, status
ORDER BY action_type, count DESC;

-- Daily verification stats for dashboards
CREATE OR REPLACE VIEW daily_verification_stats AS
SELECT
    DATE(verified_at) as date,
    action_type,
    COUNT(*) FILTER (WHERE status = 'verified') as verified_count,
    COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
    COUNT(*) FILTER (WHERE status IN ('timeout', 'error')) as error_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'verified') / NULLIF(COUNT(*), 0),
        2
    ) as success_rate,
    AVG(duration_ms) as avg_duration_ms
FROM action_verifications
WHERE verified_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(verified_at), action_type
ORDER BY date DESC, action_type;

-- Function to record verification result
CREATE OR REPLACE FUNCTION record_verification(
    p_action_type VARCHAR(50),
    p_external_id VARCHAR(255),
    p_status VARCHAR(20),
    p_attempts INTEGER DEFAULT 1,
    p_reason TEXT DEFAULT NULL,
    p_duration_ms FLOAT DEFAULT NULL,
    p_account VARCHAR(50) DEFAULT NULL,
    p_action_id UUID DEFAULT NULL,
    p_actual_state JSONB DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO action_verifications (
        action_type, external_id, status, attempts,
        reason, duration_ms, account, action_id, actual_state
    ) VALUES (
        p_action_type, p_external_id, p_status, p_attempts,
        p_reason, p_duration_ms, p_account, p_action_id, p_actual_state
    )
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Comment on table
COMMENT ON TABLE action_verifications IS
    'Tracks verification results for external API actions to ensure Jarvis does not report success when actions fail';
