-- Migration: 037_memory_privacy_controls.sql
-- Task: T-20260205-218-memory-privacy-controls
-- Purpose: Add privacy controls for memory system (GDPR/CCPA compatible)
-- Date: 2026-02-06

-- Privacy preferences table (user-level settings)
CREATE TABLE IF NOT EXISTS user_privacy_preferences (
    user_id TEXT PRIMARY KEY,
    global_settings JSONB NOT NULL DEFAULT '{
        "memory_enabled": true,
        "cross_session_learning": true,
        "long_term_storage": true,
        "share_with_team_members": false,
        "contribute_to_training": false,
        "analytics_opt_in": false
    }'::jsonb,
    layer_controls JSONB NOT NULL DEFAULT '{
        "L1_session": {"enabled": true, "ttl_override": null, "auto_promote_to_L2": true},
        "L2_contextual": {"enabled": true, "ttl_override": null, "categories_blocked": []},
        "L3_permanent": {"enabled": true, "require_explicit_consent": true, "categories_allowed": ["preferences", "skills"]}
    }'::jsonb,
    sensitivity_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_filters JSONB NOT NULL DEFAULT '{
        "blocked_content_types": ["personal_identifiers", "financial_data", "biometric_data"],
        "redaction_rules": []
    }'::jsonb,
    ttl_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Audit trail table for memory operations
CREATE TABLE IF NOT EXISTS memory_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    user_id TEXT,
    memory_id UUID,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_ip INET,
    user_agent TEXT
);

-- Consent tracking table (GDPR compliance)
CREATE TABLE IF NOT EXISTS user_consent_log (
    consent_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    consent_type TEXT NOT NULL,
    consent_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    consent_status TEXT NOT NULL CHECK (consent_status IN ('given', 'withdrawn')),
    consent_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consent_mechanism TEXT NOT NULL DEFAULT 'explicit_opt_in',
    expiry_date TIMESTAMPTZ,
    associated_processing TEXT[]
);

-- Privacy violations log (for compliance tracking)
CREATE TABLE IF NOT EXISTS privacy_violation_log (
    violation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    violation_type TEXT NOT NULL,
    affected_user_id TEXT,
    affected_memory_ids UUID[],
    severity_level TEXT NOT NULL CHECK (severity_level IN ('low', 'medium', 'high', 'critical')),
    detection_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolution_status TEXT DEFAULT 'open' CHECK (resolution_status IN ('open', 'investigating', 'resolved', 'acknowledged')),
    resolution_actions JSONB,
    resolution_timestamp TIMESTAMPTZ
);

-- Sensitivity classification cache (for performance)
CREATE TABLE IF NOT EXISTS sensitivity_classification_cache (
    content_hash TEXT PRIMARY KEY,
    sensitivity_level TEXT NOT NULL CHECK (sensitivity_level IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    classification_score FLOAT NOT NULL,
    classification_factors JSONB NOT NULL DEFAULT '{}'::jsonb,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '1 hour')
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_audit_log_user_timestamp
    ON memory_audit_log(user_id, event_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_type
    ON memory_audit_log(event_type, event_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_consent_log_user_type
    ON user_consent_log(user_id, consent_type);

CREATE INDEX IF NOT EXISTS idx_consent_log_status
    ON user_consent_log(consent_status, consent_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_violation_log_severity
    ON privacy_violation_log(severity_level, detection_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_violation_log_status
    ON privacy_violation_log(resolution_status);

CREATE INDEX IF NOT EXISTS idx_sensitivity_cache_expires
    ON sensitivity_classification_cache(expires_at);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_privacy_preferences_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for auto-updating timestamp
DROP TRIGGER IF EXISTS update_privacy_preferences_updated_at ON user_privacy_preferences;
CREATE TRIGGER update_privacy_preferences_updated_at
    BEFORE UPDATE ON user_privacy_preferences
    FOR EACH ROW
    EXECUTE FUNCTION update_privacy_preferences_timestamp();

-- Function to log privacy events
CREATE OR REPLACE FUNCTION log_privacy_event(
    p_event_type TEXT,
    p_user_id TEXT,
    p_memory_id UUID DEFAULT NULL,
    p_event_data JSONB DEFAULT '{}'::jsonb
) RETURNS UUID AS $$
DECLARE
    v_audit_id UUID;
BEGIN
    INSERT INTO memory_audit_log (event_type, user_id, memory_id, event_data)
    VALUES (p_event_type, p_user_id, p_memory_id, p_event_data)
    RETURNING audit_id INTO v_audit_id;

    RETURN v_audit_id;
END;
$$ LANGUAGE plpgsql;

-- Function to check if user has given consent
CREATE OR REPLACE FUNCTION has_active_consent(
    p_user_id TEXT,
    p_consent_type TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_has_consent BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1 FROM user_consent_log
        WHERE user_id = p_user_id
          AND consent_type = p_consent_type
          AND consent_status = 'given'
          AND (expiry_date IS NULL OR expiry_date > NOW())
        ORDER BY consent_timestamp DESC
        LIMIT 1
    ) INTO v_has_consent;

    RETURN v_has_consent;
END;
$$ LANGUAGE plpgsql;

-- Function to get user privacy preferences with defaults
CREATE OR REPLACE FUNCTION get_user_privacy_preferences(p_user_id TEXT)
RETURNS user_privacy_preferences AS $$
DECLARE
    v_prefs user_privacy_preferences;
BEGIN
    SELECT * INTO v_prefs FROM user_privacy_preferences WHERE user_id = p_user_id;

    IF NOT FOUND THEN
        -- Return default preferences
        INSERT INTO user_privacy_preferences (user_id)
        VALUES (p_user_id)
        ON CONFLICT (user_id) DO NOTHING
        RETURNING * INTO v_prefs;

        -- If still not found (race condition), fetch again
        IF NOT FOUND THEN
            SELECT * INTO v_prefs FROM user_privacy_preferences WHERE user_id = p_user_id;
        END IF;
    END IF;

    RETURN v_prefs;
END;
$$ LANGUAGE plpgsql;

-- Cleanup old sensitivity cache entries (call periodically)
CREATE OR REPLACE FUNCTION cleanup_sensitivity_cache()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM sensitivity_classification_cache
    WHERE expires_at < NOW();

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions (adjust as needed for your setup)
-- GRANT SELECT, INSERT, UPDATE ON user_privacy_preferences TO jarvis_app;
-- GRANT SELECT, INSERT ON memory_audit_log TO jarvis_app;
-- GRANT SELECT, INSERT, UPDATE ON user_consent_log TO jarvis_app;
-- GRANT SELECT, INSERT, UPDATE ON privacy_violation_log TO jarvis_app;
-- GRANT SELECT, INSERT, DELETE ON sensitivity_classification_cache TO jarvis_app;
