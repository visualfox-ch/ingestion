-- Phase 22A-05: Work Agent (WorkJarvis)
-- Date: 2026-03-19
-- Task: T-22A-05

-- =============================================================================
-- Focus Sessions (Pomodoro-style time tracking)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_focus_sessions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    task_id VARCHAR(100),                -- Optional link to external task
    task_title VARCHAR(200),
    project VARCHAR(100),
    category VARCHAR(50),                -- deep_work, meetings, admin, creative, learning
    planned_minutes INTEGER DEFAULT 25,
    actual_minutes INTEGER,
    breaks_taken INTEGER DEFAULT 0,
    interruptions INTEGER DEFAULT 0,
    energy_before INTEGER,               -- 1-10
    energy_after INTEGER,
    focus_quality INTEGER,               -- 1-10 self-assessed
    completed BOOLEAN DEFAULT FALSE,
    notes TEXT,
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_focus_sessions_user_date
ON jarvis_focus_sessions(user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_focus_sessions_project
ON jarvis_focus_sessions(project);

-- =============================================================================
-- Task Prioritization
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_work_tasks (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    external_id VARCHAR(100),            -- Link to Asana/Linear/etc
    title VARCHAR(300) NOT NULL,
    description TEXT,
    project VARCHAR(100),
    priority INTEGER DEFAULT 50,         -- 1-100, higher = more urgent
    importance INTEGER DEFAULT 50,       -- 1-100, Eisenhower matrix
    urgency INTEGER DEFAULT 50,          -- 1-100
    estimated_minutes INTEGER,
    actual_minutes INTEGER,
    due_date DATE,
    status VARCHAR(20) DEFAULT 'todo',   -- todo, in_progress, blocked, done, cancelled
    blocked_reason TEXT,
    energy_required VARCHAR(20),         -- low, medium, high
    context_tags JSONB DEFAULT '[]',     -- ["home", "office", "calls", "computer"]
    dependencies JSONB DEFAULT '[]',     -- Other task IDs
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_work_tasks_user_status
ON jarvis_work_tasks(user_id, status);

CREATE INDEX IF NOT EXISTS idx_work_tasks_priority
ON jarvis_work_tasks(priority DESC) WHERE status = 'todo';

CREATE INDEX IF NOT EXISTS idx_work_tasks_due
ON jarvis_work_tasks(due_date) WHERE status IN ('todo', 'in_progress');

-- =============================================================================
-- Effort Estimates (for learning/calibration)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_effort_estimates (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    task_id INTEGER REFERENCES jarvis_work_tasks(id),
    task_type VARCHAR(50),               -- coding, writing, review, meeting, admin
    complexity VARCHAR(20),              -- simple, moderate, complex, unknown
    estimated_minutes INTEGER NOT NULL,
    actual_minutes INTEGER,
    accuracy_pct FLOAT,                  -- Calculated after completion
    factors JSONB DEFAULT '{}',          -- {"interruptions": 2, "scope_creep": true}
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_effort_estimates_type
ON jarvis_effort_estimates(task_type);

-- =============================================================================
-- Break Tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_breaks (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    break_type VARCHAR(30),              -- micro (2-5min), short (5-15min), long (15-30min), meal
    duration_minutes INTEGER,
    activity VARCHAR(100),               -- walk, stretch, coffee, snack, social
    focus_session_id INTEGER REFERENCES jarvis_focus_sessions(id),
    energy_before INTEGER,
    energy_after INTEGER,
    suggested BOOLEAN DEFAULT FALSE,     -- Was this break suggested by Jarvis?
    taken_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_breaks_user_date
ON jarvis_breaks(user_id, taken_at DESC);

-- =============================================================================
-- Daily Work Summary
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_work_daily_summary (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    summary_date DATE DEFAULT CURRENT_DATE,
    total_focus_minutes INTEGER DEFAULT 0,
    total_break_minutes INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    tasks_created INTEGER DEFAULT 0,
    avg_focus_quality FLOAT,
    top_project VARCHAR(100),
    energy_trend VARCHAR(20),            -- rising, stable, declining
    productivity_score INTEGER,          -- 1-100
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, summary_date)
);

-- =============================================================================
-- Work Patterns (for suggestions)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_work_patterns (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    pattern_type VARCHAR(50),            -- peak_hours, break_frequency, task_batching
    pattern_data JSONB NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    sample_size INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, pattern_type)
);

-- =============================================================================
-- Seed: Default Work Patterns
-- =============================================================================

INSERT INTO jarvis_work_patterns (user_id, pattern_type, pattern_data, confidence)
VALUES
    ('1', 'peak_hours', '{"morning": [9, 11], "afternoon": [14, 16]}', 0.3),
    ('1', 'break_frequency', '{"ideal_interval_minutes": 52, "ideal_break_minutes": 17}', 0.3),
    ('1', 'task_batching', '{"similar_tasks_together": true, "context_switching_cost_minutes": 15}', 0.3)
ON CONFLICT (user_id, pattern_type) DO NOTHING;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE jarvis_focus_sessions IS 'Phase 22A-05: WorkJarvis focus time tracking';
COMMENT ON TABLE jarvis_work_tasks IS 'Phase 22A-05: WorkJarvis task prioritization';
COMMENT ON TABLE jarvis_effort_estimates IS 'Phase 22A-05: WorkJarvis effort estimation learning';
COMMENT ON TABLE jarvis_breaks IS 'Phase 22A-05: WorkJarvis break tracking';
COMMENT ON TABLE jarvis_work_daily_summary IS 'Phase 22A-05: WorkJarvis daily productivity summary';
COMMENT ON TABLE jarvis_work_patterns IS 'Phase 22A-05: WorkJarvis learned work patterns';
