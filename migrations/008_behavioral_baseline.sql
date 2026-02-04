-- Migration 008: User Behavioral Baseline for Person Intelligence
-- Phase 17.1: Jarvis learns individual work patterns, stress indicators, and activity patterns
--
-- Tables needed by person_intelligence.py:
-- 1. user_behavioral_baseline - Generic behavioral metric tracking
-- 2. user_preferences - Learned user preferences
-- 3. active_learning_queue - Questions for active learning
-- 4. user_anomaly_log - Detected behavioral anomalies
-- 5. user_activity_event - Raw activity events (new for Phase 17.1)

-- =============================================================================
-- Table 1: User Behavioral Baseline (generic metric tracking)
-- Used by BaselineTracker in person_intelligence.py
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_behavioral_baseline (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,

    -- Metric identification
    metric_category TEXT NOT NULL,           -- e.g., 'response_time', 'activity', 'communication'
    metric_name TEXT NOT NULL,               -- e.g., 'email', 'telegram', 'morning_activity'

    -- Statistical baseline (Welford's algorithm)
    expected_value FLOAT DEFAULT 0.0,
    std_dev FLOAT DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0,
    min_observed FLOAT,
    max_observed FLOAT,

    -- Confidence and filtering
    confidence FLOAT DEFAULT 0.0,            -- 0-1, based on sample_count
    context_filter JSONB DEFAULT '{}',       -- Optional context for this baseline

    -- Meta
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),

    -- Unique constraint for user + metric + context
    UNIQUE(user_id, metric_category, metric_name, context_filter)
);

CREATE INDEX IF NOT EXISTS idx_baseline_user ON user_behavioral_baseline(user_id);
CREATE INDEX IF NOT EXISTS idx_baseline_category ON user_behavioral_baseline(metric_category);
CREATE INDEX IF NOT EXISTS idx_baseline_confidence ON user_behavioral_baseline(confidence);

-- =============================================================================
-- Table 2: User Preferences
-- Used by PreferenceEngine in person_intelligence.py
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,

    -- Preference identification
    preference_category TEXT NOT NULL,       -- e.g., 'communication_style', 'detail_level', 'negative'
    preference_key TEXT NOT NULL,            -- e.g., 'formality', 'default', 'no_emojis'
    preference_value JSONB,                  -- The actual preference value

    -- Confidence tracking
    confidence FLOAT DEFAULT 0.5,
    positive_signals INTEGER DEFAULT 0,
    negative_signals INTEGER DEFAULT 0,

    -- Learning source
    learned_from TEXT DEFAULT 'inferred',    -- 'inferred', 'explicit', 'edited'

    -- Optional context
    context_type TEXT,                       -- e.g., 'project', 'person', 'channel'
    context_id TEXT,                         -- e.g., 'project_alpha', 'john@example.com'

    -- Meta
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Unique constraint
    UNIQUE(user_id, preference_category, preference_key,
           COALESCE(context_type, ''), COALESCE(context_id, ''))
);

CREATE INDEX IF NOT EXISTS idx_preferences_user ON user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_preferences_category ON user_preferences(preference_category);
CREATE INDEX IF NOT EXISTS idx_preferences_confidence ON user_preferences(confidence);
CREATE INDEX IF NOT EXISTS idx_preferences_context ON user_preferences(context_type, context_id);

-- =============================================================================
-- Table 3: Active Learning Queue
-- Used by ActiveLearner in person_intelligence.py
-- =============================================================================
CREATE TABLE IF NOT EXISTS active_learning_queue (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,

    -- Question details
    question_type TEXT NOT NULL,             -- 'preference', 'clarification', 'feedback'
    question_text TEXT NOT NULL,
    options JSONB,                           -- Array of {label, value} options
    priority FLOAT DEFAULT 0.5,              -- Higher = more important

    -- Target preference to update
    target_preference_key TEXT,              -- e.g., 'communication_style:formality'
    uncertainty_reason TEXT,                 -- Why we're asking

    -- Status tracking
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'asked', 'answered', 'expired', 'skipped')),
    answer_value JSONB,                      -- The user's answer
    asked_at TIMESTAMP,
    answered_at TIMESTAMP,
    expires_at TIMESTAMP,

    -- Meta
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learning_user ON active_learning_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_learning_status ON active_learning_queue(status);
CREATE INDEX IF NOT EXISTS idx_learning_priority ON active_learning_queue(priority DESC);
CREATE INDEX IF NOT EXISTS idx_learning_expires ON active_learning_queue(expires_at);

-- =============================================================================
-- Table 4: User Anomaly Log
-- Used by AnomalyDetector in person_intelligence.py
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_anomaly_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    baseline_id INTEGER REFERENCES user_behavioral_baseline(id),

    -- Anomaly details
    observed_value FLOAT,
    expected_value FLOAT,
    std_dev FLOAT,
    deviation_score FLOAT,                   -- Z-score
    severity TEXT DEFAULT 'elevated' CHECK (severity IN ('elevated', 'critical')),

    -- Context
    context_snapshot JSONB DEFAULT '{}',

    -- Resolution
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'explained', 'false_positive', 'new_normal')),
    explanation TEXT,
    resolved_at TIMESTAMP,

    -- Notification tracking
    notification_sent BOOLEAN DEFAULT FALSE,
    notification_sent_at TIMESTAMP,

    -- Meta
    detected_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anomaly_user ON user_anomaly_log(user_id);
CREATE INDEX IF NOT EXISTS idx_anomaly_status ON user_anomaly_log(status);
CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON user_anomaly_log(severity);
CREATE INDEX IF NOT EXISTS idx_anomaly_detected ON user_anomaly_log(detected_at DESC);

-- =============================================================================
-- Table 5: User Activity Events (NEW for Phase 17.1)
-- Raw events for baseline calculation and anomaly detection
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_activity_event (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,

    -- Event details
    event_type TEXT NOT NULL CHECK (event_type IN (
        'message_sent',
        'message_received',
        'email_sent',
        'email_received',
        'meeting_started',
        'meeting_ended',
        'task_completed',
        'login',
        'logout'
    )),
    event_timestamp TIMESTAMP NOT NULL,

    -- Context
    channel TEXT,                            -- telegram, email, calendar, etc.
    metadata JSONB DEFAULT '{}',             -- Additional event-specific data

    -- For response time calculation
    response_to_event_id INTEGER REFERENCES user_activity_event(id),
    response_time_mins FLOAT,                -- Calculated response time

    -- Processing status
    processed_for_baseline BOOLEAN DEFAULT FALSE,

    -- Meta
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_user ON user_activity_event(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_type ON user_activity_event(event_type);
CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON user_activity_event(event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_activity_unprocessed ON user_activity_event(processed_for_baseline)
    WHERE processed_for_baseline = FALSE;
CREATE INDEX IF NOT EXISTS idx_activity_user_time ON user_activity_event(user_id, event_timestamp DESC);

-- =============================================================================
-- Helper view: User Profile Summary
-- =============================================================================
CREATE OR REPLACE VIEW v_user_profile_summary AS
SELECT
    ub.user_id,
    COUNT(DISTINCT ub.metric_category || ':' || ub.metric_name) as baseline_count,
    AVG(ub.confidence) as avg_baseline_confidence,
    (SELECT COUNT(*) FROM user_preferences up WHERE up.user_id = ub.user_id) as preference_count,
    (SELECT COUNT(*) FROM user_anomaly_log ua WHERE ua.user_id = ub.user_id AND ua.status = 'open') as open_anomalies,
    MAX(ub.last_updated) as last_baseline_update
FROM user_behavioral_baseline ub
GROUP BY ub.user_id;

-- =============================================================================
-- Migration status tracking
-- =============================================================================
INSERT INTO thread_migration_status (migration_name, status, started_at)
VALUES ('008_behavioral_baseline', 'completed', NOW())
ON CONFLICT (migration_name) DO UPDATE SET
    status = 'completed',
    completed_at = NOW();
