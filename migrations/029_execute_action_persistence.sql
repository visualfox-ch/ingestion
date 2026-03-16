-- Migration 029: Execute Action persistence (requests + audit trail)

CREATE TABLE IF NOT EXISTS execute_action_request (
    request_id TEXT PRIMARY KEY,
    requester_id TEXT NOT NULL,
    requester_email TEXT,
    action_type TEXT NOT NULL,
    action_target TEXT NOT NULL,
    action_parameters JSONB NOT NULL,
    risk_level TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    decision TEXT,
    decision_maker TEXT,
    decision_reason TEXT,
    telegram_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decision_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execute_action_request_status
    ON execute_action_request(status);
CREATE INDEX IF NOT EXISTS idx_execute_action_request_requester
    ON execute_action_request(requester_id);

CREATE TABLE IF NOT EXISTS execute_action_audit (
    id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES execute_action_request(request_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execute_action_audit_request_id
    ON execute_action_audit(request_id);
