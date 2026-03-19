-- Phase 22A-06: Communication Agent (CommJarvis)
-- Date: 2026-03-19
-- Task: T-22A-06

-- =============================================================================
-- Relationship Tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_relationships (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    contact_name VARCHAR(200) NOT NULL,
    contact_email VARCHAR(200),
    contact_phone VARCHAR(50),
    relationship_type VARCHAR(50),       -- friend, family, colleague, client, mentor, acquaintance
    company VARCHAR(200),
    role VARCHAR(200),
    how_met TEXT,
    importance INTEGER DEFAULT 50,       -- 1-100
    interaction_frequency VARCHAR(20),   -- daily, weekly, monthly, quarterly, yearly
    last_contact_date DATE,
    next_followup_date DATE,
    notes TEXT,
    tags JSONB DEFAULT '[]',
    social_links JSONB DEFAULT '{}',     -- {"linkedin": "...", "twitter": "..."}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, contact_email)
);

CREATE INDEX IF NOT EXISTS idx_relationships_user
ON jarvis_relationships(user_id);

CREATE INDEX IF NOT EXISTS idx_relationships_followup
ON jarvis_relationships(next_followup_date) WHERE next_followup_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_relationships_type
ON jarvis_relationships(relationship_type);

-- =============================================================================
-- Interaction History
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_interactions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    relationship_id INTEGER REFERENCES jarvis_relationships(id),
    contact_name VARCHAR(200),
    interaction_type VARCHAR(30),        -- email, call, meeting, message, social, in_person
    direction VARCHAR(10),               -- inbound, outbound
    channel VARCHAR(50),                 -- gmail, telegram, whatsapp, linkedin, phone
    subject VARCHAR(300),
    summary TEXT,
    sentiment VARCHAR(20),               -- positive, neutral, negative
    action_items JSONB DEFAULT '[]',
    followup_needed BOOLEAN DEFAULT FALSE,
    followup_date DATE,
    interaction_date TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interactions_user_date
ON jarvis_interactions(user_id, interaction_date DESC);

CREATE INDEX IF NOT EXISTS idx_interactions_relationship
ON jarvis_interactions(relationship_id);

CREATE INDEX IF NOT EXISTS idx_interactions_followup
ON jarvis_interactions(followup_date) WHERE followup_needed = TRUE;

-- =============================================================================
-- Inbox Triage (message prioritization)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_inbox_items (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    source VARCHAR(50) NOT NULL,         -- gmail, telegram, whatsapp, slack
    message_id VARCHAR(200),
    sender_name VARCHAR(200),
    sender_email VARCHAR(200),
    subject VARCHAR(300),
    preview TEXT,
    priority INTEGER DEFAULT 50,         -- 1-100
    category VARCHAR(50),                -- urgent, important, fyi, newsletter, spam
    suggested_action VARCHAR(50),        -- reply_now, reply_later, delegate, archive, delete
    relationship_id INTEGER REFERENCES jarvis_relationships(id),
    is_from_important_contact BOOLEAN DEFAULT FALSE,
    requires_response BOOLEAN DEFAULT FALSE,
    response_deadline TIMESTAMP,
    triaged BOOLEAN DEFAULT FALSE,
    acted_on BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMP,
    triaged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inbox_user_triaged
ON jarvis_inbox_items(user_id, triaged);

CREATE INDEX IF NOT EXISTS idx_inbox_priority
ON jarvis_inbox_items(priority DESC) WHERE NOT acted_on;

-- =============================================================================
-- Response Drafts
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_response_drafts (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    inbox_item_id INTEGER REFERENCES jarvis_inbox_items(id),
    interaction_id INTEGER REFERENCES jarvis_interactions(id),
    recipient_name VARCHAR(200),
    recipient_email VARCHAR(200),
    channel VARCHAR(50),
    subject VARCHAR(300),
    draft_content TEXT NOT NULL,
    tone VARCHAR(30),                    -- formal, friendly, brief, detailed
    context_used JSONB DEFAULT '{}',     -- What context was used to generate
    version INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'draft',  -- draft, reviewed, sent, discarded
    created_at TIMESTAMP DEFAULT NOW(),
    sent_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_drafts_user_status
ON jarvis_response_drafts(user_id, status);

-- =============================================================================
-- Followup Reminders
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_followups (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    relationship_id INTEGER REFERENCES jarvis_relationships(id),
    contact_name VARCHAR(200),
    reason TEXT NOT NULL,
    followup_type VARCHAR(30),           -- check_in, thank_you, request, reminder, birthday
    due_date DATE NOT NULL,
    channel VARCHAR(50),                 -- email, call, message
    draft_message TEXT,
    priority INTEGER DEFAULT 50,
    status VARCHAR(20) DEFAULT 'pending', -- pending, completed, skipped, rescheduled
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_followups_due
ON jarvis_followups(due_date) WHERE status = 'pending';

-- =============================================================================
-- Communication Patterns
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_comm_patterns (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    pattern_type VARCHAR(50),            -- response_time, active_hours, preferred_channel
    pattern_data JSONB NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    sample_size INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, pattern_type)
);

-- Seed default patterns
INSERT INTO jarvis_comm_patterns (user_id, pattern_type, pattern_data, confidence)
VALUES
    ('1', 'response_time', '{"urgent_hours": 2, "important_hours": 24, "normal_hours": 48}', 0.3),
    ('1', 'active_hours', '{"weekday": [9, 18], "weekend": [10, 14]}', 0.3),
    ('1', 'preferred_channel', '{"work": "email", "personal": "whatsapp", "quick": "telegram"}', 0.3)
ON CONFLICT (user_id, pattern_type) DO NOTHING;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE jarvis_relationships IS 'Phase 22A-06: CommJarvis relationship tracking';
COMMENT ON TABLE jarvis_interactions IS 'Phase 22A-06: CommJarvis interaction history';
COMMENT ON TABLE jarvis_inbox_items IS 'Phase 22A-06: CommJarvis inbox triage';
COMMENT ON TABLE jarvis_response_drafts IS 'Phase 22A-06: CommJarvis response drafts';
COMMENT ON TABLE jarvis_followups IS 'Phase 22A-06: CommJarvis followup reminders';
COMMENT ON TABLE jarvis_comm_patterns IS 'Phase 22A-06: CommJarvis learned communication patterns';
