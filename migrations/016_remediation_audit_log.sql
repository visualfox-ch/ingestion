-- Migration 016: Remediation Audit Log Table
-- Phase 16.3: Automated Remediation Infrastructure
-- Created: 2026-02-01

-- =============================================================================
-- REMEDIATION AUDIT LOG TABLE
-- =============================================================================
-- Purpose: Track all remediation attempts, successes, failures, and rollbacks
-- Retention: Permanent (for forensic analysis)
-- Index strategy: Query by playbook, status, timestamp

CREATE TABLE IF NOT EXISTS remediation_audit_log (
    -- Primary identification
    id SERIAL PRIMARY KEY,
    remediation_id VARCHAR(255) UNIQUE NOT NULL,  -- rem-20260201-001
    
    -- Playbook metadata
    playbook VARCHAR(100) NOT NULL,  -- cache_invalidation, index_optimization, etc.
    tier INT NOT NULL CHECK (tier IN (1, 2, 3)),  -- 1=auto, 2=approval, 3=escalation
    
    -- Trigger information
    triggered_by VARCHAR(50) NOT NULL,  -- 'automated', 'manual', 'user:micha'
    trigger_condition TEXT NOT NULL,  -- "cache_hit_rate < 50% for 5+ minutes"
    trigger_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Approval workflow (Tier 2/3 only)
    approval_required BOOLEAN DEFAULT FALSE,
    approved_by VARCHAR(100),  -- user_id who approved
    approved_at TIMESTAMP,
    approval_reason TEXT,  -- optional comment from approver
    rejected_by VARCHAR(100),  -- if rejected
    rejected_at TIMESTAMP,
    rejection_reason TEXT,
    
    -- Execution tracking
    execution_started_at TIMESTAMP,
    execution_completed_at TIMESTAMP,
    execution_duration_seconds FLOAT,
    execution_status VARCHAR(50),  -- 'success', 'rolled_back', 'failed', 'pending_approval', 'rejected'
    
    -- Metrics before remediation
    metrics_before JSONB,  -- Full snapshot: {cache_hit_rate: 0.42, p95_latency: 850, ...}
    
    -- Metrics after remediation
    metrics_after JSONB,  -- Full snapshot after execution
    
    -- Improvement tracking
    improvement_percentage FLOAT,  -- Calculated: (after - before) / before * 100
    success_criteria_met BOOLEAN,  -- Did remediation meet expected improvement?
    
    -- Changes made
    changes TEXT[],  -- Array of change descriptions
    affected_services TEXT[],  -- ['qdrant', 'postgres', 'cache']
    
    -- Rollback information
    rollback_attempted BOOLEAN DEFAULT FALSE,
    rollback_succeeded BOOLEAN,
    rollback_timestamp TIMESTAMP,
    rollback_reason TEXT,
    
    -- Error tracking
    error_message TEXT,
    error_stacktrace TEXT,
    error_code VARCHAR(50),
    
    -- Escalation tracking
    escalated BOOLEAN DEFAULT FALSE,
    escalated_to VARCHAR(100),  -- 'ops_team', 'user:micha'
    escalated_at TIMESTAMP,
    escalation_reason TEXT,
    
    -- Audit metadata
    audit_data JSONB,  -- Full context for forensic analysis
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Query by playbook type
CREATE INDEX IF NOT EXISTS idx_remediation_playbook 
    ON remediation_audit_log(playbook);

-- Query by execution status
CREATE INDEX IF NOT EXISTS idx_remediation_status 
    ON remediation_audit_log(execution_status);

-- Query by time range (most common)
CREATE INDEX IF NOT EXISTS idx_remediation_created_at 
    ON remediation_audit_log(created_at DESC);

-- Query pending approvals
CREATE INDEX IF NOT EXISTS idx_remediation_pending_approval 
    ON remediation_audit_log(approval_required, approved_at)
    WHERE approval_required = TRUE AND approved_at IS NULL AND rejected_at IS NULL;

-- Query escalations
CREATE INDEX IF NOT EXISTS idx_remediation_escalated 
    ON remediation_audit_log(escalated, escalated_at)
    WHERE escalated = TRUE;

-- Composite index for common queries
CREATE INDEX IF NOT EXISTS idx_remediation_playbook_status_time 
    ON remediation_audit_log(playbook, execution_status, created_at DESC);

-- =============================================================================
-- HELPER FUNCTION: Generate Remediation ID
-- =============================================================================

CREATE OR REPLACE FUNCTION generate_remediation_id()
RETURNS TEXT AS $$
DECLARE
    today TEXT;
    sequence_num INT;
    remediation_id TEXT;
BEGIN
    -- Format: rem-YYYYMMDD-NNN (e.g., rem-20260201-001)
    today := TO_CHAR(NOW(), 'YYYYMMDD');
    
    -- Get next sequence number for today
    SELECT COALESCE(MAX(
        CAST(SPLIT_PART(remediation_id, '-', 3) AS INT)
    ), 0) + 1
    INTO sequence_num
    FROM remediation_audit_log
    WHERE remediation_id LIKE 'rem-' || today || '-%';
    
    -- Build ID
    remediation_id := 'rem-' || today || '-' || LPAD(sequence_num::TEXT, 3, '0');
    
    RETURN remediation_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGER: Auto-update updated_at timestamp
-- =============================================================================

CREATE OR REPLACE FUNCTION update_remediation_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER remediation_audit_log_updated_at
    BEFORE UPDATE ON remediation_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION update_remediation_updated_at();

-- =============================================================================
-- VIEW: Pending Approvals
-- =============================================================================

CREATE OR REPLACE VIEW remediation_pending_approvals AS
SELECT 
    remediation_id,
    playbook,
    tier,
    trigger_condition,
    trigger_timestamp,
    metrics_before,
    EXTRACT(EPOCH FROM (NOW() - trigger_timestamp)) / 3600 AS hours_pending,
    audit_data
FROM remediation_audit_log
WHERE 
    approval_required = TRUE 
    AND approved_at IS NULL 
    AND rejected_at IS NULL
ORDER BY trigger_timestamp ASC;

-- =============================================================================
-- VIEW: Recent Remediations (Last 7 days)
-- =============================================================================

CREATE OR REPLACE VIEW remediation_recent AS
SELECT 
    remediation_id,
    playbook,
    tier,
    execution_status,
    execution_started_at,
    execution_duration_seconds,
    improvement_percentage,
    rollback_attempted,
    escalated,
    created_at
FROM remediation_audit_log
WHERE created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;

-- =============================================================================
-- VIEW: Remediation Success Rates
-- =============================================================================

CREATE OR REPLACE VIEW remediation_success_rates AS
SELECT 
    playbook,
    COUNT(*) AS total_attempts,
    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) AS successful,
    SUM(CASE WHEN execution_status = 'rolled_back' THEN 1 ELSE 0 END) AS rolled_back,
    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) AS failed,
    ROUND(
        100.0 * SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) / COUNT(*),
        2
    ) AS success_rate_pct,
    AVG(execution_duration_seconds) AS avg_duration_seconds,
    AVG(improvement_percentage) AS avg_improvement_pct
FROM remediation_audit_log
WHERE execution_status IS NOT NULL
GROUP BY playbook
ORDER BY total_attempts DESC;

-- =============================================================================
-- SAMPLE DATA (for testing)
-- =============================================================================

-- Insert a sample remediation (for testing only, remove in production)
INSERT INTO remediation_audit_log (
    remediation_id,
    playbook,
    tier,
    triggered_by,
    trigger_condition,
    trigger_timestamp,
    approval_required,
    execution_status,
    metrics_before,
    metrics_after,
    improvement_percentage,
    success_criteria_met,
    changes,
    affected_services
) VALUES (
    'rem-20260201-001',
    'cache_invalidation',
    1,
    'automated',
    'cache_hit_rate < 50% for 5+ minutes',
    NOW() - INTERVAL '1 hour',
    FALSE,
    'success',
    '{"cache_hit_rate": 0.42, "p95_latency_ms": 850}'::jsonb,
    '{"cache_hit_rate": 0.67, "p95_latency_ms": 620}'::jsonb,
    59.5,  -- (0.67 - 0.42) / 0.42 * 100
    TRUE,
    ARRAY['Removed 1024 cache entries > 24h old', 'Freed 1GB memory'],
    ARRAY['cache', 'memory']
) ON CONFLICT (remediation_id) DO NOTHING;

-- =============================================================================
-- GRANT PERMISSIONS
-- =============================================================================

-- Grant read/write to application user
GRANT SELECT, INSERT, UPDATE ON remediation_audit_log TO jarvis_app;
GRANT SELECT ON remediation_pending_approvals TO jarvis_app;
GRANT SELECT ON remediation_recent TO jarvis_app;
GRANT SELECT ON remediation_success_rates TO jarvis_app;
GRANT USAGE ON SEQUENCE remediation_audit_log_id_seq TO jarvis_app;

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Verify table created
SELECT 
    'Remediation audit log table created' AS status,
    COUNT(*) AS sample_rows
FROM remediation_audit_log;
