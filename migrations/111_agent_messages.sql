-- Migration 111: Agent Message Schema (Tier 3 #9)
-- Standardized inter-agent communication protocol
-- Enables specialists to communicate, delegate, and share context

-- Message types enum-like check
-- Types: request, response, notification, broadcast, handoff, context_share

-- Agent Messages - core message store
CREATE TABLE IF NOT EXISTS jarvis_agent_messages (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(50) NOT NULL UNIQUE,  -- UUID for external reference

    -- Routing
    from_agent VARCHAR(50) NOT NULL,          -- 'jarvis', 'fit', 'work', 'comm', etc.
    to_agent VARCHAR(50),                      -- NULL = broadcast
    reply_to_id VARCHAR(50),                   -- For threading responses

    -- Content
    message_type VARCHAR(30) NOT NULL DEFAULT 'notification',
    subject VARCHAR(200),                      -- Brief description
    content JSONB NOT NULL,                    -- Structured message content
    priority VARCHAR(20) DEFAULT 'normal',     -- low, normal, high, urgent

    -- Context
    session_id VARCHAR(100),
    user_id VARCHAR(50),
    related_query TEXT,                        -- Original user query if relevant

    -- Status
    status VARCHAR(30) DEFAULT 'pending',      -- pending, delivered, read, processed, expired
    delivered_at TIMESTAMP,
    read_at TIMESTAMP,
    processed_at TIMESTAMP,
    expires_at TIMESTAMP,                      -- For time-sensitive messages

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Message content schema definition
COMMENT ON COLUMN jarvis_agent_messages.content IS 'Structured content: {
  "intent": "request_info|delegate_task|share_context|ask_question|provide_answer",
  "payload": { ... specific to intent ... },
  "expected_response": "required|optional|none",
  "timeout_seconds": 30
}';

-- Message Templates - reusable message patterns
CREATE TABLE IF NOT EXISTS jarvis_message_templates (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,

    -- Template
    from_agent_pattern VARCHAR(50),            -- Which agent uses this
    to_agent_pattern VARCHAR(50),              -- Typical recipient
    message_type VARCHAR(30),
    subject_template VARCHAR(200),
    content_template JSONB NOT NULL,

    -- Usage
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Agent Communication Channels - which agents can talk to which
CREATE TABLE IF NOT EXISTS jarvis_agent_channels (
    id SERIAL PRIMARY KEY,
    from_agent VARCHAR(50) NOT NULL,
    to_agent VARCHAR(50) NOT NULL,

    -- Channel config
    enabled BOOLEAN DEFAULT TRUE,
    bidirectional BOOLEAN DEFAULT TRUE,
    allowed_message_types JSONB DEFAULT '["notification", "request", "context_share"]'::jsonb,
    rate_limit_per_hour INTEGER DEFAULT 100,

    -- Stats
    messages_sent INTEGER DEFAULT 0,
    messages_received INTEGER DEFAULT 0,
    last_message_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(from_agent, to_agent)
);

-- Message Queue - for async processing
CREATE TABLE IF NOT EXISTS jarvis_message_queue (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(50) NOT NULL REFERENCES jarvis_agent_messages(message_id),

    -- Queue management
    queue_name VARCHAR(50) DEFAULT 'default',
    priority INTEGER DEFAULT 100,              -- Lower = higher priority

    -- Processing
    status VARCHAR(30) DEFAULT 'queued',       -- queued, processing, completed, failed, retrying
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    last_attempt_at TIMESTAMP,
    next_attempt_at TIMESTAMP,
    error_message TEXT,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_agent_messages_from ON jarvis_agent_messages(from_agent);
CREATE INDEX IF NOT EXISTS idx_agent_messages_to ON jarvis_agent_messages(to_agent);
CREATE INDEX IF NOT EXISTS idx_agent_messages_status ON jarvis_agent_messages(status);
CREATE INDEX IF NOT EXISTS idx_agent_messages_type ON jarvis_agent_messages(message_type);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON jarvis_agent_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_reply ON jarvis_agent_messages(reply_to_id);
CREATE INDEX IF NOT EXISTS idx_message_queue_status ON jarvis_message_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_message_queue_next ON jarvis_message_queue(next_attempt_at) WHERE status IN ('queued', 'retrying');

-- Seed default channels between specialists
INSERT INTO jarvis_agent_channels (from_agent, to_agent, bidirectional, allowed_message_types)
VALUES
    ('jarvis', 'fit', TRUE, '["notification", "request", "response", "context_share", "handoff"]'::jsonb),
    ('jarvis', 'work', TRUE, '["notification", "request", "response", "context_share", "handoff"]'::jsonb),
    ('jarvis', 'comm', TRUE, '["notification", "request", "response", "context_share", "handoff"]'::jsonb),
    ('fit', 'work', TRUE, '["notification", "request", "context_share"]'::jsonb),
    ('fit', 'comm', TRUE, '["notification", "request", "context_share"]'::jsonb),
    ('work', 'comm', TRUE, '["notification", "request", "context_share"]'::jsonb)
ON CONFLICT (from_agent, to_agent) DO NOTHING;

-- Seed common message templates
INSERT INTO jarvis_message_templates (template_name, description, from_agent_pattern, to_agent_pattern, message_type, subject_template, content_template)
VALUES
(
    'schedule_check',
    'Ask WorkJarvis about calendar availability',
    'fit',
    'work',
    'request',
    'Kalender-Check für Training',
    '{
        "intent": "request_info",
        "payload": {
            "info_type": "calendar_availability",
            "date_range": "today",
            "purpose": "training"
        },
        "expected_response": "required",
        "timeout_seconds": 10
    }'::jsonb
),
(
    'context_handoff',
    'Share context when switching specialists',
    NULL,
    NULL,
    'handoff',
    'Kontext-Übergabe',
    '{
        "intent": "share_context",
        "payload": {
            "previous_specialist": null,
            "context_summary": null,
            "relevant_facts": [],
            "user_mood": null
        },
        "expected_response": "none"
    }'::jsonb
),
(
    'delegate_communication',
    'WorkJarvis delegates communication task to CommJarvis',
    'work',
    'comm',
    'request',
    'Kommunikationsaufgabe',
    '{
        "intent": "delegate_task",
        "payload": {
            "task_type": "communication",
            "details": null,
            "deadline": null,
            "priority": "normal"
        },
        "expected_response": "required",
        "timeout_seconds": 30
    }'::jsonb
),
(
    'fitness_reminder',
    'FitJarvis sends a fitness reminder',
    'fit',
    'jarvis',
    'notification',
    'Fitness-Erinnerung',
    '{
        "intent": "notification",
        "payload": {
            "reminder_type": "workout",
            "message": null,
            "suggested_action": null
        },
        "expected_response": "none"
    }'::jsonb
)
ON CONFLICT (template_name) DO NOTHING;

COMMENT ON TABLE jarvis_agent_messages IS 'Inter-agent message store (Tier 3 #9)';
COMMENT ON TABLE jarvis_message_templates IS 'Reusable message patterns for common agent interactions';
COMMENT ON TABLE jarvis_agent_channels IS 'Defines allowed communication paths between agents';
COMMENT ON TABLE jarvis_message_queue IS 'Async message processing queue';
