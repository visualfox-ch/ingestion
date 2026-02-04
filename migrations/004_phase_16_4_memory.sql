-- Phase 16.4C: Memory System Tables
-- Migration: 004_phase_16_4_memory.sql
-- Created: 2026-02-01
-- Author: Claude Code

-- =============================================================================
-- PERSONAL TIMELINE
-- =============================================================================

CREATE TABLE IF NOT EXISTS personal_timeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Event identification
    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',
    event_type VARCHAR(100) NOT NULL,  -- 'meeting', 'decision', 'milestone', 'note', 'pattern'

    -- Event details
    title VARCHAR(500) NOT NULL,
    description TEXT,
    context TEXT,  -- Additional context for recall

    -- Temporal
    event_date DATE NOT NULL,
    event_time TIME,

    -- Classification
    category VARCHAR(100),  -- 'work', 'personal', 'health', 'learning'
    importance INT DEFAULT 3,  -- 1=critical, 2=high, 3=normal, 4=low, 5=trivial

    -- References
    related_entities JSONB,  -- [{type: 'person', name: 'Max', id: 'xyz'}]
    source_type VARCHAR(50),  -- 'chat', 'email', 'calendar', 'manual'
    source_id VARCHAR(200),  -- Original ID if from external source

    -- Metadata
    tags TEXT[],
    is_private BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- USER PREFERENCES (Learning)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_learned_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',

    -- Preference identification
    preference_key VARCHAR(200) NOT NULL,  -- 'communication_style', 'meeting_times', 'coffee_order'
    preference_category VARCHAR(100),  -- 'work', 'personal', 'food', 'schedule'

    -- Learned value
    preference_value TEXT NOT NULL,
    confidence DECIMAL(3,2) DEFAULT 0.50,  -- 0.0-1.0 confidence level

    -- Learning tracking
    observation_count INT DEFAULT 1,
    first_observed_at TIMESTAMPTZ DEFAULT NOW(),
    last_confirmed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Source evidence
    evidence JSONB,  -- [{date, source, context}]

    -- Metadata
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, preference_key)
);

-- =============================================================================
-- BEHAVIOR PATTERNS
-- =============================================================================

CREATE TABLE IF NOT EXISTS detected_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',

    -- Pattern identification
    pattern_type VARCHAR(100) NOT NULL,  -- 'daily_routine', 'weekly_cycle', 'response_pattern'
    pattern_name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Pattern data
    pattern_data JSONB NOT NULL,  -- Structured pattern information
    confidence DECIMAL(3,2) DEFAULT 0.50,

    -- Temporal scope
    time_scope VARCHAR(50),  -- 'daily', 'weekly', 'monthly', 'situational'
    applicable_days INT[],  -- 1=Monday, 7=Sunday (for weekly patterns)

    -- Tracking
    observation_count INT DEFAULT 1,
    last_matched_at TIMESTAMPTZ,
    false_positive_count INT DEFAULT 0,

    -- Status
    is_active BOOLEAN DEFAULT true,
    is_confirmed BOOLEAN DEFAULT false,  -- User confirmed pattern

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INTERACTION QUALITY TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS interaction_quality (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Interaction reference
    session_id VARCHAR(100),
    message_id VARCHAR(100),
    timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Quality signals
    response_helpful BOOLEAN,  -- Did user indicate helpfulness?
    task_completed BOOLEAN,    -- Was the task completed?
    follow_up_needed BOOLEAN,  -- Did user need clarification?

    -- Implicit signals
    response_length INT,       -- User's response length (short = satisfied?)
    response_time_seconds INT, -- How long until user responded
    conversation_continued BOOLEAN,  -- Did conversation continue on same topic?

    -- Explicit feedback
    rating INT,  -- 1-5 if provided
    feedback_text TEXT,

    -- Context
    query_type VARCHAR(100),  -- 'search', 'draft', 'analyze', 'chat'
    namespace VARCHAR(100),

    -- Analysis
    inferred_satisfaction DECIMAL(3,2),  -- 0.0-1.0 computed satisfaction

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- RELATIONSHIP NOTES
-- =============================================================================

CREATE TABLE IF NOT EXISTS relationship_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id VARCHAR(100) NOT NULL DEFAULT 'micha',

    -- Person identification
    person_name VARCHAR(200) NOT NULL,
    person_email VARCHAR(200),
    person_company VARCHAR(200),
    relationship_type VARCHAR(100),  -- 'colleague', 'client', 'friend', 'family'

    -- Notes
    notes TEXT,

    -- Learned facts
    learned_facts JSONB,  -- [{fact, confidence, source}]
    communication_preferences JSONB,  -- {preferred_channel, response_style}

    -- Importance
    vip_status BOOLEAN DEFAULT false,
    interaction_frequency VARCHAR(50),  -- 'daily', 'weekly', 'monthly', 'rare'

    -- Last interaction
    last_interaction_date DATE,
    last_interaction_type VARCHAR(100),
    last_interaction_summary TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Timeline indexes
CREATE INDEX IF NOT EXISTS idx_timeline_user_date ON personal_timeline(user_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_timeline_type ON personal_timeline(event_type);
CREATE INDEX IF NOT EXISTS idx_timeline_category ON personal_timeline(category);
CREATE INDEX IF NOT EXISTS idx_timeline_importance ON personal_timeline(importance);
CREATE INDEX IF NOT EXISTS idx_timeline_tags ON personal_timeline USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_timeline_entities ON personal_timeline USING GIN(related_entities);

-- Preferences indexes
CREATE INDEX IF NOT EXISTS idx_preferences_user ON user_learned_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_preferences_category ON user_learned_preferences(preference_category);
CREATE INDEX IF NOT EXISTS idx_preferences_key ON user_learned_preferences(preference_key);

-- Pattern indexes
CREATE INDEX IF NOT EXISTS idx_patterns_user ON detected_patterns(user_id);
CREATE INDEX IF NOT EXISTS idx_patterns_type ON detected_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_patterns_active ON detected_patterns(is_active);

-- Quality indexes
CREATE INDEX IF NOT EXISTS idx_quality_session ON interaction_quality(session_id);
CREATE INDEX IF NOT EXISTS idx_quality_timestamp ON interaction_quality(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_quality_namespace ON interaction_quality(namespace);

-- Relationship indexes
CREATE INDEX IF NOT EXISTS idx_relationships_user ON relationship_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_relationships_person ON relationship_notes(person_name);
CREATE INDEX IF NOT EXISTS idx_relationships_vip ON relationship_notes(vip_status);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to update preference confidence based on observations
CREATE OR REPLACE FUNCTION update_preference_confidence(
    p_user_id VARCHAR(100),
    p_key VARCHAR(200),
    p_value TEXT,
    p_source TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_existing RECORD;
    v_new_confidence DECIMAL(3,2);
BEGIN
    -- Get existing preference
    SELECT * INTO v_existing
    FROM user_learned_preferences
    WHERE user_id = p_user_id AND preference_key = p_key;

    IF FOUND THEN
        -- Same value -> increase confidence
        IF v_existing.preference_value = p_value THEN
            v_new_confidence := LEAST(v_existing.confidence + 0.1, 1.0);
            UPDATE user_learned_preferences SET
                confidence = v_new_confidence,
                observation_count = observation_count + 1,
                last_confirmed_at = NOW(),
                evidence = evidence || jsonb_build_array(jsonb_build_object(
                    'date', NOW(),
                    'source', COALESCE(p_source, 'observation'),
                    'value', p_value
                )),
                updated_at = NOW()
            WHERE id = v_existing.id;
        ELSE
            -- Different value -> decrease confidence or update
            IF v_existing.confidence < 0.5 THEN
                -- Low confidence, replace value
                UPDATE user_learned_preferences SET
                    preference_value = p_value,
                    confidence = 0.5,
                    observation_count = observation_count + 1,
                    evidence = jsonb_build_array(jsonb_build_object(
                        'date', NOW(),
                        'source', COALESCE(p_source, 'observation'),
                        'value', p_value
                    )),
                    updated_at = NOW()
                WHERE id = v_existing.id;
            ELSE
                -- High confidence, just decrease
                UPDATE user_learned_preferences SET
                    confidence = GREATEST(confidence - 0.1, 0.3),
                    updated_at = NOW()
                WHERE id = v_existing.id;
            END IF;
        END IF;
    ELSE
        -- Insert new preference
        INSERT INTO user_learned_preferences (
            user_id, preference_key, preference_value, confidence, evidence
        ) VALUES (
            p_user_id, p_key, p_value, 0.5,
            jsonb_build_array(jsonb_build_object(
                'date', NOW(),
                'source', COALESCE(p_source, 'observation'),
                'value', p_value
            ))
        );
    END IF;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to record timeline event
CREATE OR REPLACE FUNCTION record_timeline_event(
    p_user_id VARCHAR(100),
    p_event_type VARCHAR(100),
    p_title VARCHAR(500),
    p_description TEXT DEFAULT NULL,
    p_event_date DATE DEFAULT CURRENT_DATE,
    p_category VARCHAR(100) DEFAULT NULL,
    p_importance INT DEFAULT 3,
    p_tags TEXT[] DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO personal_timeline (
        user_id, event_type, title, description, event_date, category, importance, tags
    ) VALUES (
        p_user_id, p_event_type, p_title, p_description, p_event_date, p_category, p_importance, p_tags
    ) RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Add comments for tracking
COMMENT ON TABLE personal_timeline IS 'Phase 16.4C: Personal events and milestones timeline';
COMMENT ON TABLE user_learned_preferences IS 'Phase 16.4C: Learned user preferences with confidence tracking';
COMMENT ON TABLE detected_patterns IS 'Phase 16.4C: Detected behavioral patterns';
COMMENT ON TABLE interaction_quality IS 'Phase 16.4C: Interaction quality tracking for learning';
COMMENT ON TABLE relationship_notes IS 'Phase 16.4C: Notes about people and relationships';
