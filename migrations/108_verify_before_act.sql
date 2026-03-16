-- Phase S2: Verify-Before-Act System
-- Disciplined flow: Plan → Execute → Verify → Handoff
-- Date: 2026-03-15

-- ============================================
-- Action Plans (Pre-execution planning)
-- ============================================

CREATE TABLE IF NOT EXISTS action_plans (
    id SERIAL PRIMARY KEY,
    plan_id TEXT UNIQUE NOT NULL DEFAULT ('plan_' || gen_random_uuid()::text),

    -- What we're doing
    action_type TEXT NOT NULL,  -- 'tool_call', 'multi_step', 'external_api', 'file_operation'
    action_name TEXT NOT NULL,  -- tool name or operation description
    action_params JSONB,        -- input parameters

    -- Expected outcomes
    expected_outcome TEXT NOT NULL,      -- human-readable expectation
    expected_state JSONB,                -- machine-checkable state
    success_criteria JSONB,              -- conditions that define success
    rollback_plan JSONB,                 -- how to undo if failed

    -- Risk assessment
    risk_tier INTEGER DEFAULT 1 CHECK (risk_tier BETWEEN 0 AND 3),
    requires_verification BOOLEAN DEFAULT TRUE,
    auto_rollback_on_failure BOOLEAN DEFAULT FALSE,

    -- Context
    context JSONB,             -- conversation context, user intent
    created_by TEXT DEFAULT 'jarvis',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Status
    status TEXT DEFAULT 'planned' CHECK (status IN ('planned', 'executing', 'executed', 'verified', 'failed', 'rolled_back'))
);

CREATE INDEX IF NOT EXISTS idx_action_plans_status ON action_plans(status);
CREATE INDEX IF NOT EXISTS idx_action_plans_type ON action_plans(action_type);
CREATE INDEX IF NOT EXISTS idx_action_plans_created ON action_plans(created_at DESC);

-- ============================================
-- Action Executions (Execution log)
-- ============================================

CREATE TABLE IF NOT EXISTS action_executions (
    id SERIAL PRIMARY KEY,
    plan_id TEXT REFERENCES action_plans(plan_id) ON DELETE CASCADE,

    -- Execution details
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    -- Actual result
    actual_outcome TEXT,          -- what actually happened
    actual_state JSONB,           -- actual resulting state
    raw_result JSONB,             -- raw tool/API response

    -- Status
    execution_status TEXT DEFAULT 'running' CHECK (execution_status IN ('running', 'success', 'partial', 'error', 'timeout')),
    error_message TEXT,
    error_details JSONB,

    -- Metadata
    executor TEXT DEFAULT 'jarvis',
    execution_context JSONB
);

CREATE INDEX IF NOT EXISTS idx_action_executions_plan ON action_executions(plan_id);
CREATE INDEX IF NOT EXISTS idx_action_executions_status ON action_executions(execution_status);

-- ============================================
-- Verification Results (Plan vs Reality)
-- ============================================

CREATE TABLE IF NOT EXISTS verification_results (
    id SERIAL PRIMARY KEY,
    plan_id TEXT REFERENCES action_plans(plan_id) ON DELETE CASCADE,
    execution_id INTEGER REFERENCES action_executions(id) ON DELETE CASCADE,

    -- Verification outcome
    verified_at TIMESTAMPTZ DEFAULT NOW(),
    verification_passed BOOLEAN NOT NULL,

    -- Detailed comparison
    criteria_results JSONB,       -- each criterion: met/not met
    discrepancies JSONB,          -- differences between expected and actual
    confidence_score FLOAT CHECK (confidence_score >= 0 AND confidence_score <= 1.0),

    -- Actions taken
    action_taken TEXT CHECK (action_taken IN ('none', 'alert_user', 'auto_rollback', 'manual_review', 'retry')),
    action_details JSONB,

    -- Human review
    human_reviewed BOOLEAN DEFAULT FALSE,
    reviewer TEXT,
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_verification_results_plan ON verification_results(plan_id);
CREATE INDEX IF NOT EXISTS idx_verification_results_passed ON verification_results(verification_passed);

-- ============================================
-- Rollback Log (When things go wrong)
-- ============================================

CREATE TABLE IF NOT EXISTS rollback_log (
    id SERIAL PRIMARY KEY,
    plan_id TEXT REFERENCES action_plans(plan_id) ON DELETE CASCADE,
    verification_id INTEGER REFERENCES verification_results(id),

    -- Rollback details
    triggered_at TIMESTAMPTZ DEFAULT NOW(),
    trigger_reason TEXT NOT NULL,  -- 'auto_failure', 'manual', 'discrepancy', 'timeout'

    -- Rollback execution
    rollback_steps JSONB,         -- steps taken
    rollback_status TEXT DEFAULT 'pending' CHECK (rollback_status IN ('pending', 'in_progress', 'success', 'partial', 'failed')),
    completed_at TIMESTAMPTZ,

    -- State recovery
    pre_rollback_state JSONB,
    post_rollback_state JSONB,
    state_recovered BOOLEAN,

    -- Notes
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_rollback_log_plan ON rollback_log(plan_id);
CREATE INDEX IF NOT EXISTS idx_rollback_log_status ON rollback_log(rollback_status);

-- ============================================
-- Useful Views
-- ============================================

-- Active plans needing attention
CREATE OR REPLACE VIEW v_active_plans AS
SELECT
    p.plan_id,
    p.action_type,
    p.action_name,
    p.expected_outcome,
    p.status,
    p.risk_tier,
    p.created_at,
    e.execution_status,
    e.completed_at as executed_at,
    v.verification_passed,
    v.action_taken
FROM action_plans p
LEFT JOIN action_executions e ON p.plan_id = e.plan_id
LEFT JOIN verification_results v ON p.plan_id = v.plan_id
WHERE p.status NOT IN ('verified', 'rolled_back')
  OR (p.status = 'verified' AND v.verification_passed = FALSE)
ORDER BY p.created_at DESC;

-- Failed verifications needing review
CREATE OR REPLACE VIEW v_failed_verifications AS
SELECT
    p.plan_id,
    p.action_name,
    p.expected_outcome,
    e.actual_outcome,
    v.discrepancies,
    v.action_taken,
    v.verified_at,
    v.human_reviewed
FROM action_plans p
JOIN action_executions e ON p.plan_id = e.plan_id
JOIN verification_results v ON p.plan_id = v.plan_id
WHERE v.verification_passed = FALSE
  AND v.human_reviewed = FALSE
ORDER BY v.verified_at DESC;

-- Verification statistics
CREATE OR REPLACE VIEW v_verification_stats AS
SELECT
    action_type,
    COUNT(*) as total_plans,
    COUNT(*) FILTER (WHERE status = 'verified') as verified_count,
    COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
    COUNT(*) FILTER (WHERE status = 'rolled_back') as rolled_back_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'verified') / NULLIF(COUNT(*), 0),
        2
    ) as success_rate_pct
FROM action_plans
GROUP BY action_type;

-- ============================================
-- Helper Functions
-- ============================================

-- Create a new action plan
CREATE OR REPLACE FUNCTION create_action_plan(
    p_action_type TEXT,
    p_action_name TEXT,
    p_action_params JSONB,
    p_expected_outcome TEXT,
    p_expected_state JSONB DEFAULT NULL,
    p_success_criteria JSONB DEFAULT NULL,
    p_rollback_plan JSONB DEFAULT NULL,
    p_risk_tier INTEGER DEFAULT 1,
    p_context JSONB DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_plan_id TEXT;
BEGIN
    INSERT INTO action_plans (
        action_type, action_name, action_params,
        expected_outcome, expected_state, success_criteria, rollback_plan,
        risk_tier, context
    ) VALUES (
        p_action_type, p_action_name, p_action_params,
        p_expected_outcome, p_expected_state, p_success_criteria, p_rollback_plan,
        p_risk_tier, p_context
    ) RETURNING plan_id INTO v_plan_id;

    RETURN v_plan_id;
END;
$$ LANGUAGE plpgsql;

-- Record execution result
CREATE OR REPLACE FUNCTION record_execution(
    p_plan_id TEXT,
    p_actual_outcome TEXT,
    p_actual_state JSONB,
    p_raw_result JSONB,
    p_status TEXT,
    p_error_message TEXT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_exec_id INTEGER;
    v_started TIMESTAMPTZ;
BEGIN
    -- Get start time
    SELECT started_at INTO v_started
    FROM action_executions
    WHERE plan_id = p_plan_id AND execution_status = 'running'
    ORDER BY started_at DESC LIMIT 1;

    IF v_started IS NULL THEN
        v_started := NOW();
    END IF;

    -- Insert or update execution
    INSERT INTO action_executions (
        plan_id, actual_outcome, actual_state, raw_result,
        execution_status, error_message, completed_at, duration_ms
    ) VALUES (
        p_plan_id, p_actual_outcome, p_actual_state, p_raw_result,
        p_status, p_error_message, NOW(),
        EXTRACT(EPOCH FROM (NOW() - v_started)) * 1000
    ) RETURNING id INTO v_exec_id;

    -- Update plan status
    UPDATE action_plans
    SET status = CASE
        WHEN p_status = 'success' THEN 'executed'
        WHEN p_status = 'error' THEN 'failed'
        ELSE 'executed'
    END
    WHERE plan_id = p_plan_id;

    RETURN v_exec_id;
END;
$$ LANGUAGE plpgsql;

-- Verify execution against plan
CREATE OR REPLACE FUNCTION verify_execution(
    p_plan_id TEXT,
    p_execution_id INTEGER DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    v_plan RECORD;
    v_exec RECORD;
    v_passed BOOLEAN;
    v_confidence FLOAT;
    v_discrepancies JSONB;
    v_criteria_results JSONB;
    v_action TEXT;
    v_result_id INTEGER;
BEGIN
    -- Get plan
    SELECT * INTO v_plan FROM action_plans WHERE plan_id = p_plan_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'Plan not found');
    END IF;

    -- Get execution (latest if not specified)
    IF p_execution_id IS NULL THEN
        SELECT * INTO v_exec FROM action_executions
        WHERE plan_id = p_plan_id ORDER BY completed_at DESC LIMIT 1;
    ELSE
        SELECT * INTO v_exec FROM action_executions WHERE id = p_execution_id;
    END IF;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'Execution not found');
    END IF;

    -- Simple verification: check if execution was successful
    -- More complex verification can compare expected_state vs actual_state
    v_passed := (v_exec.execution_status = 'success');
    v_confidence := CASE
        WHEN v_exec.execution_status = 'success' THEN 0.9
        WHEN v_exec.execution_status = 'partial' THEN 0.5
        ELSE 0.1
    END;

    -- Build discrepancies (simplified)
    v_discrepancies := jsonb_build_object(
        'expected_outcome', v_plan.expected_outcome,
        'actual_outcome', v_exec.actual_outcome,
        'status_match', v_exec.execution_status = 'success'
    );

    -- Determine action
    v_action := CASE
        WHEN v_passed THEN 'none'
        WHEN v_plan.auto_rollback_on_failure AND NOT v_passed THEN 'auto_rollback'
        WHEN v_plan.risk_tier >= 2 AND NOT v_passed THEN 'alert_user'
        ELSE 'manual_review'
    END;

    -- Record verification
    INSERT INTO verification_results (
        plan_id, execution_id, verification_passed,
        criteria_results, discrepancies, confidence_score, action_taken
    ) VALUES (
        p_plan_id, v_exec.id, v_passed,
        v_criteria_results, v_discrepancies, v_confidence, v_action
    ) RETURNING id INTO v_result_id;

    -- Update plan status
    UPDATE action_plans
    SET status = CASE WHEN v_passed THEN 'verified' ELSE 'failed' END
    WHERE plan_id = p_plan_id;

    RETURN jsonb_build_object(
        'verification_id', v_result_id,
        'passed', v_passed,
        'confidence', v_confidence,
        'action_taken', v_action,
        'discrepancies', v_discrepancies
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Comments
-- ============================================

COMMENT ON TABLE action_plans IS 'S2: Pre-execution planning with expected outcomes';
COMMENT ON TABLE action_executions IS 'S2: Execution log with actual results';
COMMENT ON TABLE verification_results IS 'S2: Comparison of plan vs reality';
COMMENT ON TABLE rollback_log IS 'S2: Log of rollback actions when verification fails';
COMMENT ON VIEW v_active_plans IS 'S2: Plans needing attention';
COMMENT ON VIEW v_failed_verifications IS 'S2: Failed verifications needing review';
COMMENT ON FUNCTION create_action_plan IS 'S2: Create a new action plan before execution';
COMMENT ON FUNCTION record_execution IS 'S2: Record execution result';
COMMENT ON FUNCTION verify_execution IS 'S2: Verify execution against plan';
