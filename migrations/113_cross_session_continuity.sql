-- Migration 113: Cross-Session Continuity (Tier 3 #11)
-- Enables agents to remember context from previous sessions
-- "Where did we leave off?" becomes automatic

-- Session summaries - condensed memory of each session
CREATE TABLE IF NOT EXISTS jarvis_session_summaries (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(50),

    -- Session metadata
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_minutes INTEGER,

    -- Summary content
    summary TEXT,                               -- AI-generated summary of session
    key_topics JSONB DEFAULT '[]'::jsonb,       -- ["fitness", "work", "calendar"]
    decisions_made JSONB DEFAULT '[]'::jsonb,   -- Important decisions from session
    action_items JSONB DEFAULT '[]'::jsonb,     -- Follow-up items

    -- Specialist involvement
    specialists_used JSONB DEFAULT '[]'::jsonb, -- ["fit", "work"]
    primary_specialist VARCHAR(50),             -- Most active specialist

    -- Context for next session
    open_threads JSONB DEFAULT '[]'::jsonb,     -- Unfinished conversations
    user_state_snapshot JSONB,                  -- Energy, mood, etc. at end

    -- Stats
    message_count INTEGER DEFAULT 0,
    tool_calls_count INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Conversation threads - track ongoing topics across sessions
CREATE TABLE IF NOT EXISTS jarvis_conversation_threads (
    id SERIAL PRIMARY KEY,
    thread_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(50),

    -- Thread identity
    topic VARCHAR(200) NOT NULL,                -- "Fitness-Ziel: 5kg abnehmen"
    category VARCHAR(50),                       -- fitness, work, personal, health
    specialist VARCHAR(50),                     -- Primary specialist for this thread

    -- State
    status VARCHAR(20) DEFAULT 'active',        -- active, paused, resolved, archived
    priority INTEGER DEFAULT 50,                -- 1-100, higher = more important

    -- Content
    context_summary TEXT,                       -- Current state of discussion
    last_message_preview TEXT,                  -- Last thing discussed
    milestones JSONB DEFAULT '[]'::jsonb,       -- Progress markers

    -- Lifecycle
    first_session_id VARCHAR(100),
    last_session_id VARCHAR(100),
    session_count INTEGER DEFAULT 1,

    -- Timing
    last_active_at TIMESTAMP DEFAULT NOW(),
    remind_after TIMESTAMP,                     -- Optional reminder

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Session handoffs - explicit context passed between sessions
CREATE TABLE IF NOT EXISTS jarvis_session_handoffs (
    id SERIAL PRIMARY KEY,

    -- Session links
    from_session_id VARCHAR(100) NOT NULL,
    to_session_id VARCHAR(100),                 -- NULL until next session claims it
    user_id VARCHAR(50),

    -- Handoff content
    handoff_type VARCHAR(50) NOT NULL,          -- context, reminder, follow_up, escalation
    priority INTEGER DEFAULT 50,

    -- The actual handoff data
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,

    -- Specialist context
    from_specialist VARCHAR(50),
    for_specialist VARCHAR(50),                 -- Target specialist (or NULL for any)

    -- Status
    status VARCHAR(20) DEFAULT 'pending',       -- pending, delivered, expired, dismissed
    delivered_at TIMESTAMP,

    -- Lifecycle
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- User session preferences - how the user likes to continue
CREATE TABLE IF NOT EXISTS jarvis_user_session_prefs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL UNIQUE,

    -- Continuity preferences
    auto_resume_threads BOOLEAN DEFAULT TRUE,   -- Resume open threads automatically
    show_session_recap BOOLEAN DEFAULT TRUE,    -- Show "last time we discussed..."
    recap_verbosity VARCHAR(20) DEFAULT 'brief', -- brief, detailed, none

    -- Thread preferences
    max_active_threads INTEGER DEFAULT 5,       -- Auto-archive old threads
    thread_reminder_enabled BOOLEAN DEFAULT TRUE,

    -- Specialist preferences
    remember_specialist_context BOOLEAN DEFAULT TRUE,
    specialist_memory_days INTEGER DEFAULT 30,  -- How long specialists remember

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_session_summaries_user ON jarvis_session_summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_session_summaries_ended ON jarvis_session_summaries(ended_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_threads_user ON jarvis_conversation_threads(user_id, status);
CREATE INDEX IF NOT EXISTS idx_conversation_threads_active ON jarvis_conversation_threads(last_active_at DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_session_handoffs_pending ON jarvis_session_handoffs(user_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_session_handoffs_to ON jarvis_session_handoffs(to_session_id) WHERE to_session_id IS NOT NULL;

-- Default user preferences
INSERT INTO jarvis_user_session_prefs (user_id, auto_resume_threads, show_session_recap, recap_verbosity)
VALUES ('1', TRUE, TRUE, 'brief')
ON CONFLICT (user_id) DO NOTHING;

COMMENT ON TABLE jarvis_session_summaries IS 'Condensed summaries of each session for continuity (Tier 3 #11)';
COMMENT ON TABLE jarvis_conversation_threads IS 'Ongoing conversation topics that span multiple sessions';
COMMENT ON TABLE jarvis_session_handoffs IS 'Explicit context handoffs between sessions';
COMMENT ON TABLE jarvis_user_session_prefs IS 'User preferences for session continuity behavior';
