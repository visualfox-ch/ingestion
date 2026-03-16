-- Migration: Night Mode Learning Database
-- Created: 2026-02-10
-- Purpose: Store implementation outcomes for RLHF-style learning

-- Implementation attempts table
CREATE TABLE IF NOT EXISTS night_mode_implementations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id VARCHAR(64) NOT NULL,
    job_id UUID,

    -- Task metadata
    task_description TEXT NOT NULL,
    task_type VARCHAR(64),  -- 'refactor', 'bugfix', 'feature', 'test', 'docs'
    risk_level INTEGER DEFAULT 0,  -- 0=R0, 1=R1, 2=R2
    acceptance_criteria JSONB,

    -- Implementation details
    code_generated TEXT,
    tests_generated TEXT,
    files_modified JSONB,  -- List of files changed

    -- TDD metrics
    attempt_number INTEGER DEFAULT 1,
    total_attempts INTEGER DEFAULT 1,
    tests_passed INTEGER DEFAULT 0,
    tests_failed INTEGER DEFAULT 0,

    -- Quality metrics
    quality_score FLOAT DEFAULT 0.0,
    safety_score FLOAT DEFAULT 0.0,

    -- Timing
    duration_ms FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Outcome
    status VARCHAR(32) DEFAULT 'pending',  -- 'pending', 'success', 'failed', 'timeout'
    error_message TEXT,
    lessons_learned JSONB  -- Array of lessons from failures
);

-- Human feedback table (RLHF-style)
CREATE TABLE IF NOT EXISTS night_mode_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    implementation_id UUID REFERENCES night_mode_implementations(id) ON DELETE CASCADE,

    -- Feedback
    decision VARCHAR(32) NOT NULL,  -- 'approved', 'rejected', 'iterate'
    feedback_text TEXT,
    improvement_suggestions JSONB,

    -- Reviewer info
    reviewer_id VARCHAR(64),
    reviewed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Learning signals
    was_helpful BOOLEAN,
    quality_rating INTEGER,  -- 1-5 stars

    CONSTRAINT valid_decision CHECK (decision IN ('approved', 'rejected', 'iterate', 'auto_approved'))
);

-- Learning patterns table (aggregated insights)
CREATE TABLE IF NOT EXISTS night_mode_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Pattern identification
    pattern_type VARCHAR(64) NOT NULL,  -- 'success', 'failure', 'improvement'
    task_type VARCHAR(64),

    -- Pattern details
    description TEXT NOT NULL,
    conditions JSONB,  -- When does this pattern apply?
    approach JSONB,  -- What approach worked?

    -- Statistics
    occurrence_count INTEGER DEFAULT 1,
    success_rate FLOAT DEFAULT 0.0,
    avg_quality_score FLOAT DEFAULT 0.0,
    avg_iterations FLOAT DEFAULT 1.0,

    -- Timestamps
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),

    -- Active flag
    is_active BOOLEAN DEFAULT true
);

-- Task similarity cache (for fast retrieval)
CREATE TABLE IF NOT EXISTS night_mode_task_similarity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Task pair
    task_a_id UUID REFERENCES night_mode_implementations(id) ON DELETE CASCADE,
    task_b_id UUID REFERENCES night_mode_implementations(id) ON DELETE CASCADE,

    -- Similarity metrics
    description_similarity FLOAT DEFAULT 0.0,  -- Cosine similarity of embeddings
    criteria_overlap FLOAT DEFAULT 0.0,  -- Jaccard similarity of criteria
    code_similarity FLOAT DEFAULT 0.0,  -- Code structure similarity
    overall_similarity FLOAT DEFAULT 0.0,

    -- Computed at
    computed_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(task_a_id, task_b_id)
);

-- Metrics aggregation view
CREATE OR REPLACE VIEW night_mode_metrics AS
SELECT
    DATE_TRUNC('day', created_at) as day,
    task_type,
    risk_level,
    COUNT(*) as total_tasks,
    COUNT(*) FILTER (WHERE status = 'success') as successful_tasks,
    AVG(quality_score) as avg_quality,
    AVG(safety_score) as avg_safety,
    AVG(total_attempts) as avg_iterations,
    AVG(duration_ms) as avg_duration_ms,
    COUNT(*) FILTER (WHERE status = 'success')::FLOAT / NULLIF(COUNT(*), 0) as success_rate
FROM night_mode_implementations
GROUP BY DATE_TRUNC('day', created_at), task_type, risk_level;

-- Approval rate tracking view
CREATE OR REPLACE VIEW night_mode_approval_rates AS
SELECT
    DATE_TRUNC('day', nf.reviewed_at) as day,
    ni.task_type,
    ni.risk_level,
    COUNT(*) as total_reviews,
    COUNT(*) FILTER (WHERE nf.decision = 'approved') as approved_count,
    COUNT(*) FILTER (WHERE nf.decision = 'rejected') as rejected_count,
    COUNT(*) FILTER (WHERE nf.decision = 'iterate') as iterate_count,
    AVG(nf.quality_rating) as avg_rating,
    COUNT(*) FILTER (WHERE nf.decision = 'approved')::FLOAT / NULLIF(COUNT(*), 0) as approval_rate
FROM night_mode_feedback nf
JOIN night_mode_implementations ni ON nf.implementation_id = ni.id
GROUP BY DATE_TRUNC('day', nf.reviewed_at), ni.task_type, ni.risk_level;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_nm_impl_task_id ON night_mode_implementations(task_id);
CREATE INDEX IF NOT EXISTS idx_nm_impl_status ON night_mode_implementations(status);
CREATE INDEX IF NOT EXISTS idx_nm_impl_task_type ON night_mode_implementations(task_type);
CREATE INDEX IF NOT EXISTS idx_nm_impl_created_at ON night_mode_implementations(created_at);
CREATE INDEX IF NOT EXISTS idx_nm_feedback_impl_id ON night_mode_feedback(implementation_id);
CREATE INDEX IF NOT EXISTS idx_nm_patterns_type ON night_mode_patterns(pattern_type, task_type);
CREATE INDEX IF NOT EXISTS idx_nm_similarity_task_a ON night_mode_task_similarity(task_a_id);
CREATE INDEX IF NOT EXISTS idx_nm_similarity_task_b ON night_mode_task_similarity(task_b_id);

-- Grant permissions
GRANT ALL ON night_mode_implementations TO jarvis;
GRANT ALL ON night_mode_feedback TO jarvis;
GRANT ALL ON night_mode_patterns TO jarvis;
GRANT ALL ON night_mode_task_similarity TO jarvis;
GRANT SELECT ON night_mode_metrics TO jarvis;
GRANT SELECT ON night_mode_approval_rates TO jarvis;
