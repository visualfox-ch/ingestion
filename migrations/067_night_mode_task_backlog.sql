-- Migration 067: Night Mode Task Backlog
-- Week 2: Task selection for autonomous execution
-- Created: 2026-02-10

-- Task backlog for Night Mode
CREATE TABLE IF NOT EXISTS night_mode_task_backlog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Task identification
    external_id VARCHAR(255),           -- Reference to external system (Asana, TASKS.md)
    source VARCHAR(50) NOT NULL,        -- 'asana', 'tasks_md', 'manual'

    -- Task details
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    acceptance_criteria JSONB NOT NULL DEFAULT '[]',  -- Array of criteria strings

    -- Risk and priority
    risk_level INTEGER NOT NULL DEFAULT 0 CHECK (risk_level >= 0 AND risk_level <= 3),
    priority INTEGER NOT NULL DEFAULT 50 CHECK (priority >= 0 AND priority <= 100),
    estimated_hours DECIMAL(4,2) DEFAULT 1.0,

    -- Eligibility
    night_mode_eligible BOOLEAN DEFAULT FALSE,
    has_external_deps BOOLEAN DEFAULT FALSE,
    requires_human_input BOOLEAN DEFAULT FALSE,

    -- Context
    file_paths JSONB DEFAULT '[]',      -- Relevant file paths
    function_names JSONB DEFAULT '[]',  -- Target functions
    task_type VARCHAR(50),              -- 'bug_fix', 'feature', 'refactor', 'test', 'docs'

    -- Status tracking
    status VARCHAR(20) DEFAULT 'todo' CHECK (status IN ('todo', 'queued', 'in_progress', 'completed', 'failed', 'skipped')),
    last_attempted_at TIMESTAMP,
    attempt_count INTEGER DEFAULT 0,

    -- Execution results
    last_result JSONB,                  -- Result from last execution
    last_error TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Night Mode execution queue (tasks selected for current night)
CREATE TABLE IF NOT EXISTS night_mode_execution_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    task_id UUID NOT NULL REFERENCES night_mode_task_backlog(id),

    -- Selection info
    night_date DATE NOT NULL DEFAULT CURRENT_DATE,
    selection_order INTEGER NOT NULL,
    selection_reason TEXT,
    confidence_estimate DECIMAL(3,2),

    -- Execution tracking
    status VARCHAR(20) DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped')),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Results
    execution_result JSONB,
    implementation_id UUID,             -- Reference to night_mode_implementations

    created_at TIMESTAMP DEFAULT NOW()
);

-- Morning review queue
CREATE TABLE IF NOT EXISTS night_mode_morning_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    night_date DATE NOT NULL,

    -- Summary
    tasks_attempted INTEGER DEFAULT 0,
    tasks_succeeded INTEGER DEFAULT 0,
    tasks_failed INTEGER DEFAULT 0,

    -- Aggregated metrics
    avg_confidence DECIMAL(3,2),
    avg_iterations DECIMAL(4,2),
    total_duration_minutes INTEGER,

    -- Review status
    review_status VARCHAR(20) DEFAULT 'pending' CHECK (review_status IN ('pending', 'reviewed', 'approved', 'rejected')),
    reviewed_at TIMESTAMP,
    reviewed_by VARCHAR(100),
    review_notes TEXT,

    -- Telegram notification
    telegram_sent BOOLEAN DEFAULT FALSE,
    telegram_message_id VARCHAR(100),

    created_at TIMESTAMP DEFAULT NOW()
);

-- Individual task review items
CREATE TABLE IF NOT EXISTS night_mode_review_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    review_id UUID NOT NULL REFERENCES night_mode_morning_reviews(id),
    execution_id UUID NOT NULL REFERENCES night_mode_execution_queue(id),

    -- Task summary
    task_title VARCHAR(500),
    task_type VARCHAR(50),
    risk_level INTEGER,

    -- Execution summary
    status VARCHAR(20),
    confidence_score DECIMAL(3,2),
    iterations INTEGER,
    duration_ms INTEGER,

    -- Code summary
    files_modified JSONB DEFAULT '[]',
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,

    -- Review
    approved BOOLEAN,
    review_notes TEXT,

    created_at TIMESTAMP DEFAULT NOW()
);

-- View: Eligible tasks for selection
CREATE OR REPLACE VIEW night_mode_eligible_tasks AS
SELECT
    t.*,
    COALESCE(
        (SELECT COUNT(*) FROM night_mode_implementations ni
         WHERE ni.task_type = t.task_type AND ni.status = 'success'),
        0
    ) AS similar_successes,
    COALESCE(
        (SELECT AVG(quality_score) FROM night_mode_implementations ni
         WHERE ni.task_type = t.task_type),
        0.0
    ) AS avg_quality_for_type
FROM night_mode_task_backlog t
WHERE t.status = 'todo'
  AND t.night_mode_eligible = TRUE
  AND t.has_external_deps = FALSE
  AND t.requires_human_input = FALSE
  AND t.risk_level <= 1  -- Only R0 and R1
  AND jsonb_array_length(t.acceptance_criteria) > 0
ORDER BY
    t.risk_level ASC,      -- Lowest risk first
    t.priority DESC,       -- Highest priority first
    t.estimated_hours ASC; -- Shortest tasks first

-- View: Tonight's execution summary
CREATE OR REPLACE VIEW night_mode_tonight_summary AS
SELECT
    eq.night_date,
    COUNT(*) AS total_tasks,
    SUM(CASE WHEN eq.status = 'completed' THEN 1 ELSE 0 END) AS completed,
    SUM(CASE WHEN eq.status = 'failed' THEN 1 ELSE 0 END) AS failed,
    SUM(CASE WHEN eq.status = 'running' THEN 1 ELSE 0 END) AS running,
    SUM(CASE WHEN eq.status = 'queued' THEN 1 ELSE 0 END) AS queued,
    AVG(eq.confidence_estimate) AS avg_confidence
FROM night_mode_execution_queue eq
WHERE eq.night_date = CURRENT_DATE
GROUP BY eq.night_date;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_nm_backlog_status ON night_mode_task_backlog(status);
CREATE INDEX IF NOT EXISTS idx_nm_backlog_eligible ON night_mode_task_backlog(night_mode_eligible, status);
CREATE INDEX IF NOT EXISTS idx_nm_backlog_risk ON night_mode_task_backlog(risk_level, priority DESC);
CREATE INDEX IF NOT EXISTS idx_nm_queue_night ON night_mode_execution_queue(night_date, selection_order);
CREATE INDEX IF NOT EXISTS idx_nm_queue_task ON night_mode_execution_queue(task_id);
CREATE INDEX IF NOT EXISTS idx_nm_reviews_night ON night_mode_morning_reviews(night_date);
CREATE INDEX IF NOT EXISTS idx_nm_review_items_review ON night_mode_review_items(review_id);

-- Grants
GRANT ALL ON night_mode_task_backlog TO jarvis;
GRANT ALL ON night_mode_execution_queue TO jarvis;
GRANT ALL ON night_mode_morning_reviews TO jarvis;
GRANT ALL ON night_mode_review_items TO jarvis;
GRANT SELECT ON night_mode_eligible_tasks TO jarvis;
GRANT SELECT ON night_mode_tonight_summary TO jarvis;

-- Grant sequence access
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jarvis;

COMMENT ON TABLE night_mode_task_backlog IS 'Task backlog for Night Mode autonomous execution';
COMMENT ON TABLE night_mode_execution_queue IS 'Tasks selected for execution on a given night';
COMMENT ON TABLE night_mode_morning_reviews IS 'Morning review summaries for human approval';
COMMENT ON TABLE night_mode_review_items IS 'Individual task review items';
