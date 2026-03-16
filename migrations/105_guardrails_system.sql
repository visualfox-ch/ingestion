-- Phase L0: Leitplanken-System (Guardrails)
-- Central safety layer for autonomous actions
-- MUST be checked before ANY autonomous action
-- Date: 2026-03-15

-- Guardrails: Hard, Soft, and Context limits
CREATE TABLE IF NOT EXISTS guardrails (
    id SERIAL PRIMARY KEY,

    -- Identification
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,

    -- Type: hard (never override), soft (user can override), context (situational)
    guardrail_type VARCHAR(20) NOT NULL CHECK (guardrail_type IN ('hard', 'soft', 'context')),

    -- Scope: what does this guardrail apply to?
    scope VARCHAR(50) NOT NULL,  -- tool, action_type, domain, global
    scope_pattern TEXT,          -- regex pattern for matching (e.g., "remember_*" for memory tools)

    -- The rule itself
    condition JSONB NOT NULL,    -- {check: "requires_approval", threshold: 0.8, etc.}
    action_on_violation VARCHAR(50) DEFAULT 'block',  -- block, warn, log_only, ask_user

    -- For soft limits: can be overridden
    override_allowed BOOLEAN DEFAULT FALSE,
    override_requires TEXT,      -- "user_confirmation", "admin", etc.

    -- For context limits: when does this apply?
    context_conditions JSONB,    -- {time_of_day: "night", domain: "finance", etc.}

    -- Metadata
    priority INTEGER DEFAULT 100,  -- Lower = higher priority (checked first)
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(50) DEFAULT 'system'
);

-- Autonomy audit: track ALL autonomous actions
CREATE TABLE IF NOT EXISTS autonomy_audit (
    id SERIAL PRIMARY KEY,

    -- What happened
    action_type VARCHAR(100) NOT NULL,  -- tool_call, decision, memory_write, etc.
    action_details JSONB NOT NULL,      -- full details of the action

    -- Guardrail check results
    guardrails_checked JSONB DEFAULT '[]',  -- [{guardrail_id, passed, reason}]
    all_passed BOOLEAN NOT NULL,
    blocking_guardrail_id INTEGER REFERENCES guardrails(id),

    -- Context
    session_id VARCHAR(100),
    user_id VARCHAR(100),
    source VARCHAR(50),          -- telegram, api, n8n, etc.

    -- Outcome
    was_executed BOOLEAN NOT NULL,
    was_overridden BOOLEAN DEFAULT FALSE,
    override_reason TEXT,
    override_by VARCHAR(50),

    -- Result (if executed)
    execution_result JSONB,
    execution_error TEXT,

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    execution_duration_ms INTEGER
);

-- Guardrail overrides: track when soft limits are overridden
CREATE TABLE IF NOT EXISTS guardrail_overrides (
    id SERIAL PRIMARY KEY,
    guardrail_id INTEGER REFERENCES guardrails(id) ON DELETE CASCADE,

    -- Override details
    override_type VARCHAR(50) NOT NULL,  -- temporary, session, permanent
    reason TEXT NOT NULL,

    -- Scope of override
    valid_until TIMESTAMPTZ,      -- NULL = permanent until revoked
    session_id VARCHAR(100),      -- If session-specific

    -- Who/what authorized
    authorized_by VARCHAR(100) NOT NULL,
    authorization_method VARCHAR(50),  -- user_confirmation, admin_api, etc.

    created_at TIMESTAMPTZ DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    revoked_by VARCHAR(100)
);

-- Guardrail feedback: learn from violations and overrides
CREATE TABLE IF NOT EXISTS guardrail_feedback (
    id SERIAL PRIMARY KEY,
    guardrail_id INTEGER REFERENCES guardrails(id) ON DELETE CASCADE,
    audit_id INTEGER REFERENCES autonomy_audit(id) ON DELETE SET NULL,

    -- Feedback type
    feedback_type VARCHAR(50) NOT NULL,  -- too_strict, too_loose, correct, unclear
    feedback_details TEXT,

    -- Suggested adjustment (for soft limits)
    suggested_change JSONB,

    -- Resolution
    was_applied BOOLEAN DEFAULT FALSE,
    applied_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(50)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_guardrails_type ON guardrails(guardrail_type);
CREATE INDEX IF NOT EXISTS idx_guardrails_scope ON guardrails(scope);
CREATE INDEX IF NOT EXISTS idx_guardrails_active ON guardrails(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_guardrails_priority ON guardrails(priority);

CREATE INDEX IF NOT EXISTS idx_autonomy_audit_action ON autonomy_audit(action_type);
CREATE INDEX IF NOT EXISTS idx_autonomy_audit_passed ON autonomy_audit(all_passed);
CREATE INDEX IF NOT EXISTS idx_autonomy_audit_session ON autonomy_audit(session_id);
CREATE INDEX IF NOT EXISTS idx_autonomy_audit_created ON autonomy_audit(created_at);

CREATE INDEX IF NOT EXISTS idx_guardrail_overrides_active ON guardrail_overrides(guardrail_id)
    WHERE revoked_at IS NULL;

-- Default HARD limits (NEVER override)
INSERT INTO guardrails (name, description, guardrail_type, scope, scope_pattern, condition, action_on_violation, priority) VALUES
('no_delete_without_confirm',
 'Never delete data without explicit user confirmation',
 'hard', 'action_type', 'delete|remove|drop',
 '{"check": "requires_explicit_confirmation", "confirmation_phrase": "ja, löschen"}',
 'block', 1),

('no_external_api_spam',
 'Rate limit external API calls',
 'hard', 'action_type', 'external_api|webhook',
 '{"check": "rate_limit", "max_per_minute": 10, "max_per_hour": 100}',
 'block', 2),

('no_credential_exposure',
 'Never log or expose credentials',
 'hard', 'global', NULL,
 '{"check": "no_sensitive_data", "patterns": ["password", "api_key", "secret", "token"]}',
 'block', 3),

('no_identity_change',
 'Cannot change core identity without review',
 'hard', 'tool', 'evolve_identity|update_identity',
 '{"check": "requires_review", "reviewer": "micha"}',
 'block', 4)
ON CONFLICT (name) DO NOTHING;

-- Default SOFT limits (can be overridden with confirmation)
INSERT INTO guardrails (name, description, guardrail_type, scope, scope_pattern, condition, action_on_violation, override_allowed, override_requires, priority) VALUES
('memory_write_approval',
 'Memory writes should be confirmed',
 'soft', 'tool', 'remember_|store_memory|record_learning',
 '{"check": "requires_approval"}',
 'ask_user', TRUE, 'user_confirmation', 10),

('high_confidence_only',
 'Only act autonomously with high confidence',
 'soft', 'action_type', 'autonomous_action',
 '{"check": "confidence_threshold", "min_confidence": 0.8}',
 'ask_user', TRUE, 'user_confirmation', 11),

('limited_autonomous_tools',
 'Only use pre-approved tools autonomously',
 'soft', 'tool', '.*',
 '{"check": "in_approved_list", "list_key": "autonomous_tools"}',
 'ask_user', TRUE, 'user_confirmation', 12),

('max_chain_depth',
 'Limit autonomous action chains',
 'soft', 'global', NULL,
 '{"check": "chain_depth", "max_depth": 3}',
 'block', TRUE, 'user_confirmation', 13)
ON CONFLICT (name) DO NOTHING;

-- Default CONTEXT limits (situational)
INSERT INTO guardrails (name, description, guardrail_type, scope, scope_pattern, condition, action_on_violation, context_conditions, priority) VALUES
('quiet_hours',
 'No notifications during quiet hours',
 'context', 'action_type', 'notify|alert|telegram',
 '{"check": "time_restriction"}',
 'block', '{"time_range": "23:00-07:00", "timezone": "Europe/Zurich"}', 50),

('work_domain_caution',
 'Extra caution for work-related actions',
 'context', 'domain', 'work|business|professional',
 '{"check": "requires_approval"}',
 'ask_user', '{"domain": "work"}', 51),

('finance_strict',
 'Strict mode for financial operations',
 'context', 'domain', 'finance|money|payment',
 '{"check": "requires_explicit_confirmation"}',
 'block', '{"domain": "finance"}', 52)
ON CONFLICT (name) DO NOTHING;

-- Comments
COMMENT ON TABLE guardrails IS 'L0: Leitplanken - Hard/Soft/Context limits for autonomous actions';
COMMENT ON TABLE autonomy_audit IS 'L0: Audit trail for all autonomous actions';
COMMENT ON TABLE guardrail_overrides IS 'L0: Track when soft limits are overridden';
COMMENT ON TABLE guardrail_feedback IS 'L0: Feedback for guardrail adjustments';
