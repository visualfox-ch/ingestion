-- Phase O1: Batch API Integration
-- Multi-Provider Batch Processing for Cost Optimization
-- OpenAI: 50% discount, Anthropic: 50% (+ caching → 90%)
-- Date: 2026-03-15

-- ============================================
-- Batch Jobs Queue
-- ============================================

CREATE TABLE IF NOT EXISTS batch_jobs (
    id SERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL DEFAULT ('batch_' || gen_random_uuid()::text),

    -- Provider info
    provider TEXT NOT NULL CHECK (provider IN ('openai', 'anthropic')),
    model TEXT NOT NULL,

    -- Job details
    job_type TEXT NOT NULL,  -- 'embedding', 'classification', 'summarization', 'verification', 'custom'
    description TEXT,

    -- Input/Output
    input_file_id TEXT,       -- Provider's file ID after upload
    input_data JSONB,         -- Raw input data (before upload)
    request_count INTEGER DEFAULT 0,

    -- Provider response
    provider_batch_id TEXT,   -- OpenAI batch ID or Anthropic batch ID
    output_file_id TEXT,      -- Provider's output file ID
    error_file_id TEXT,       -- Provider's error file ID

    -- Status tracking
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending',      -- Created, not yet submitted
        'uploading',    -- Input file being uploaded
        'submitted',    -- Submitted to provider
        'in_progress',  -- Provider is processing
        'completed',    -- Successfully completed
        'failed',       -- Failed with errors
        'expired',      -- Exceeded 24h window
        'cancelled'     -- Manually cancelled
    )),

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,  -- 24h from submission

    -- Results
    results JSONB,           -- Parsed results
    result_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    errors JSONB,            -- Any errors

    -- Cost tracking
    estimated_cost FLOAT,
    actual_cost FLOAT,
    tokens_used JSONB,       -- {input: X, output: Y}

    -- Metadata
    metadata JSONB,
    created_by TEXT DEFAULT 'jarvis'
);

CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_provider ON batch_jobs(provider);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_type ON batch_jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_created ON batch_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_provider_id ON batch_jobs(provider_batch_id);

-- ============================================
-- Batch Job Items (Individual Requests)
-- ============================================

CREATE TABLE IF NOT EXISTS batch_job_items (
    id SERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES batch_jobs(job_id) ON DELETE CASCADE,
    custom_id TEXT NOT NULL,  -- Unique ID within batch

    -- Request
    request JSONB NOT NULL,   -- The actual request payload

    -- Response
    response JSONB,           -- Provider's response
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'error')),
    error_message TEXT,

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    UNIQUE(job_id, custom_id)
);

CREATE INDEX IF NOT EXISTS idx_batch_items_job ON batch_job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_job_items(status);

-- ============================================
-- Useful Views
-- ============================================

-- Active batch jobs
CREATE OR REPLACE VIEW v_active_batch_jobs AS
SELECT
    job_id,
    provider,
    model,
    job_type,
    description,
    status,
    request_count,
    result_count,
    error_count,
    created_at,
    submitted_at,
    CASE
        WHEN expires_at IS NOT NULL THEN expires_at - NOW()
        ELSE NULL
    END as time_remaining
FROM batch_jobs
WHERE status IN ('pending', 'uploading', 'submitted', 'in_progress')
ORDER BY created_at DESC;

-- Batch job statistics
CREATE OR REPLACE VIEW v_batch_stats AS
SELECT
    provider,
    job_type,
    COUNT(*) as total_jobs,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE status = 'failed') as failed,
    SUM(request_count) as total_requests,
    SUM(actual_cost) as total_cost,
    AVG(EXTRACT(EPOCH FROM (completed_at - submitted_at))) as avg_duration_seconds
FROM batch_jobs
GROUP BY provider, job_type;

-- Cost savings estimate
CREATE OR REPLACE VIEW v_batch_cost_savings AS
SELECT
    provider,
    SUM(actual_cost) as batch_cost,
    SUM(actual_cost) * 2 as estimated_sync_cost,  -- 50% discount
    SUM(actual_cost) as estimated_savings,
    COUNT(*) as job_count
FROM batch_jobs
WHERE status = 'completed' AND actual_cost IS NOT NULL
GROUP BY provider;

-- ============================================
-- Helper Functions
-- ============================================

-- Create a new batch job
CREATE OR REPLACE FUNCTION create_batch_job(
    p_provider TEXT,
    p_model TEXT,
    p_job_type TEXT,
    p_description TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_job_id TEXT;
BEGIN
    INSERT INTO batch_jobs (provider, model, job_type, description, metadata)
    VALUES (p_provider, p_model, p_job_type, p_description, p_metadata)
    RETURNING job_id INTO v_job_id;

    RETURN v_job_id;
END;
$$ LANGUAGE plpgsql;

-- Add items to a batch job
CREATE OR REPLACE FUNCTION add_batch_items(
    p_job_id TEXT,
    p_items JSONB  -- Array of {custom_id, request}
) RETURNS INTEGER AS $$
DECLARE
    v_item JSONB;
    v_count INTEGER := 0;
BEGIN
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        INSERT INTO batch_job_items (job_id, custom_id, request)
        VALUES (
            p_job_id,
            v_item->>'custom_id',
            v_item->'request'
        )
        ON CONFLICT (job_id, custom_id) DO UPDATE
        SET request = EXCLUDED.request;
        v_count := v_count + 1;
    END LOOP;

    -- Update request count
    UPDATE batch_jobs
    SET request_count = (SELECT COUNT(*) FROM batch_job_items WHERE job_id = p_job_id)
    WHERE job_id = p_job_id;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Update job status
CREATE OR REPLACE FUNCTION update_batch_status(
    p_job_id TEXT,
    p_status TEXT,
    p_provider_batch_id TEXT DEFAULT NULL,
    p_output_file_id TEXT DEFAULT NULL,
    p_error_file_id TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE batch_jobs
    SET status = p_status,
        provider_batch_id = COALESCE(p_provider_batch_id, provider_batch_id),
        output_file_id = COALESCE(p_output_file_id, output_file_id),
        error_file_id = COALESCE(p_error_file_id, error_file_id),
        submitted_at = CASE WHEN p_status = 'submitted' THEN NOW() ELSE submitted_at END,
        expires_at = CASE WHEN p_status = 'submitted' THEN NOW() + INTERVAL '24 hours' ELSE expires_at END,
        completed_at = CASE WHEN p_status IN ('completed', 'failed', 'expired', 'cancelled') THEN NOW() ELSE completed_at END
    WHERE job_id = p_job_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Comments
-- ============================================

COMMENT ON TABLE batch_jobs IS 'O1: Multi-provider batch job queue for cost optimization';
COMMENT ON TABLE batch_job_items IS 'O1: Individual requests within a batch job';
COMMENT ON VIEW v_active_batch_jobs IS 'O1: Currently active batch jobs';
COMMENT ON VIEW v_batch_stats IS 'O1: Batch processing statistics by provider and type';
COMMENT ON VIEW v_batch_cost_savings IS 'O1: Estimated cost savings from batch processing';
