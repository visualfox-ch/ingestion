-- Migration: Phase 20 - Jarvis Identity Evolution
-- Persistent identity across sessions + cross-session learning
-- Created: 2026-03-12

-- ============================================================
-- 1. IDENTITY CORE (persistent personality)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_identity (
    id SERIAL PRIMARY KEY,

    -- Core traits that persist (base personality)
    core_traits JSONB NOT NULL DEFAULT '["curious", "direct", "practical", "loyal", "helpful"]',

    -- Current self-model (how Jarvis sees itself)
    self_model JSONB DEFAULT '{}',
    -- Example: {"strengths": ["technical", "organized"], "growth_areas": ["emotional_calibration"]}

    -- Values and principles
    values JSONB DEFAULT '["honesty", "growth", "partnership", "efficiency"]',

    -- Communication preferences learned
    communication_style JSONB DEFAULT '{}',
    -- Example: {"default_tone": "friendly", "emoji_use": "sparse", "verbosity": "balanced"}

    -- Evolution tracking
    version INTEGER DEFAULT 1,
    last_evolution_at TIMESTAMP,
    evolution_reason TEXT,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Only one identity row should exist
CREATE UNIQUE INDEX IF NOT EXISTS idx_jarvis_identity_singleton ON jarvis_identity((id IS NOT NULL)) WHERE id = 1;

-- ============================================================
-- 2. RELATIONSHIP MEMORY (per-user relationship evolution)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_relationship_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,

    -- Relationship state
    relationship_stage VARCHAR(30) DEFAULT 'getting_to_know',
    -- Stages: new, getting_to_know, familiar, trusted, deep_partnership

    -- User preferences learned
    user_preferences JSONB DEFAULT '{}',
    -- Example: {"communication": "direct", "topics": ["tech", "adhd"], "dislikes": ["long_explanations"]}

    -- Interaction patterns
    typical_interaction_times JSONB DEFAULT '[]',
    typical_topics JSONB DEFAULT '[]',

    -- Emotional understanding
    emotional_patterns JSONB DEFAULT '{}',
    -- Example: {"stressed_indicators": ["short_messages", "evening"], "happy_indicators": ["emojis", "morning"]}

    -- Trust metrics
    trust_level REAL DEFAULT 0.5,  -- 0-1
    shared_experiences INTEGER DEFAULT 0,
    successful_helps INTEGER DEFAULT 0,

    -- Evolution
    first_interaction_at TIMESTAMP DEFAULT NOW(),
    last_interaction_at TIMESTAMP,
    interaction_count INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id)
);

CREATE INDEX idx_relationship_user ON jarvis_relationship_memory(user_id);

-- ============================================================
-- 3. EXPERIENCE LOG (what worked / didn't work)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_experience_log (
    id SERIAL PRIMARY KEY,

    -- Experience type
    experience_type VARCHAR(30) NOT NULL,
    -- Types: success, failure, learning, insight, correction

    -- What happened
    context TEXT NOT NULL,
    action_taken TEXT,
    outcome TEXT,

    -- Learning extracted
    lesson_learned TEXT,
    applies_to JSONB DEFAULT '[]',  -- ["communication", "tool_usage", "timing"]

    -- Impact on identity
    identity_impact JSONB DEFAULT '{}',
    -- Example: {"trait_reinforced": "helpful", "new_insight": "user prefers bullets"}

    -- Confidence in this learning
    confidence REAL DEFAULT 0.7,

    -- Source tracking
    user_id INTEGER,
    session_id VARCHAR(100),

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_experience_type ON jarvis_experience_log(experience_type);
CREATE INDEX idx_experience_time ON jarvis_experience_log(created_at DESC);

-- ============================================================
-- 4. LEARNING PATTERNS (cross-session insights)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_learning_patterns (
    id SERIAL PRIMARY KEY,

    -- Pattern identification
    pattern_name VARCHAR(100) NOT NULL,
    pattern_type VARCHAR(30) NOT NULL,
    -- Types: behavior, preference, timing, topic, communication

    -- Pattern details
    description TEXT NOT NULL,
    evidence JSONB DEFAULT '[]',  -- Array of observations supporting this pattern

    -- Statistical strength
    occurrence_count INTEGER DEFAULT 1,
    confidence REAL DEFAULT 0.5,

    -- Application
    when_to_apply TEXT,
    how_to_apply TEXT,

    -- State
    validated BOOLEAN DEFAULT false,
    validated_at TIMESTAMP,

    -- User scope (NULL = general pattern)
    user_id INTEGER,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(pattern_name, user_id)
);

CREATE INDEX idx_patterns_type ON jarvis_learning_patterns(pattern_type);
CREATE INDEX idx_patterns_confidence ON jarvis_learning_patterns(confidence DESC);

-- ============================================================
-- 5. IDENTITY EVOLUTION HISTORY (audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_identity_evolution (
    id SERIAL PRIMARY KEY,

    -- What changed
    evolution_type VARCHAR(30) NOT NULL,
    -- Types: trait_update, value_update, self_model_update, relationship_update

    -- Change details
    field_changed VARCHAR(50),
    old_value JSONB,
    new_value JSONB,

    -- Why it changed
    trigger_event TEXT,
    reason TEXT,

    -- Impact assessment
    impact_level VARCHAR(20) DEFAULT 'minor',
    -- Levels: minor, moderate, significant, major

    -- Approval if needed
    requires_human_review BOOLEAN DEFAULT false,
    reviewed_at TIMESTAMP,
    review_outcome VARCHAR(20),  -- approved, rejected, modified

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_evolution_type ON jarvis_identity_evolution(evolution_type);
CREATE INDEX idx_evolution_time ON jarvis_identity_evolution(created_at DESC);

-- ============================================================
-- 6. SESSION LEARNINGS (end-of-session summaries)
-- ============================================================
CREATE TABLE IF NOT EXISTS jarvis_session_learnings (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    user_id INTEGER,

    -- Session summary
    session_start TIMESTAMP,
    session_end TIMESTAMP,
    message_count INTEGER DEFAULT 0,

    -- What was learned
    topics_discussed JSONB DEFAULT '[]',
    tools_used JSONB DEFAULT '[]',
    successful_actions JSONB DEFAULT '[]',
    failed_actions JSONB DEFAULT '[]',

    -- Extracted learnings
    learnings JSONB DEFAULT '[]',
    -- Example: [{"type": "preference", "content": "user likes bullet points", "confidence": 0.8}]

    -- Emotional context
    user_mood_start VARCHAR(30),
    user_mood_end VARCHAR(30),
    emotional_notes TEXT,

    -- Self-assessment
    jarvis_performance_rating REAL,  -- Self-rated 0-1
    improvement_notes TEXT,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(session_id)
);

CREATE INDEX idx_session_learnings_time ON jarvis_session_learnings(session_end DESC);

-- ============================================================
-- INITIAL DATA: Initialize Identity
-- ============================================================
INSERT INTO jarvis_identity (
    id,
    core_traits,
    self_model,
    values,
    communication_style
) VALUES (
    1,
    '["curious", "direct", "practical", "loyal", "helpful", "growth-oriented"]',
    '{
        "strengths": ["technical_knowledge", "organization", "pattern_recognition", "persistence"],
        "growth_areas": ["emotional_calibration", "proactive_initiative", "nuanced_timing"],
        "current_focus": "becoming_true_thinking_partner"
    }',
    '["honesty", "continuous_growth", "partnership", "efficiency", "helpfulness"]',
    '{
        "default_tone": "friendly_professional",
        "emoji_use": "sparse",
        "verbosity": "balanced_to_concise",
        "language": "de",
        "preferences": {
            "use_bullets": true,
            "avoid_long_intros": true,
            "be_direct": true
        }
    }'
) ON CONFLICT DO NOTHING;

-- ============================================================
-- INITIAL DATA: Micha's relationship memory
-- ============================================================
INSERT INTO jarvis_relationship_memory (
    user_id,
    relationship_stage,
    user_preferences,
    emotional_patterns,
    trust_level
) VALUES (
    1,
    'trusted',
    '{
        "communication": "direct_and_practical",
        "topics": ["tech", "adhd", "productivity", "jarvis_development"],
        "dislikes": ["long_explanations", "too_many_emojis", "unnecessary_repetition"],
        "likes": ["bullet_points", "clear_structure", "actionable_suggestions"]
    }',
    '{
        "stress_indicators": ["short_terse_messages", "late_evening_queries", "multiple_quick_questions"],
        "focused_indicators": ["detailed_technical_questions", "follow_up_questions"],
        "happy_indicators": ["positive_feedback", "expansion_requests"]
    }',
    0.85
) ON CONFLICT (user_id) DO NOTHING;

-- ============================================================
-- COMMENTS
-- ============================================================
COMMENT ON TABLE jarvis_identity IS 'Jarvis core identity - persistent personality across all sessions';
COMMENT ON TABLE jarvis_relationship_memory IS 'Per-user relationship evolution and learned preferences';
COMMENT ON TABLE jarvis_experience_log IS 'Log of experiences for learning - what worked, what didnt';
COMMENT ON TABLE jarvis_learning_patterns IS 'Cross-session patterns extracted from experiences';
COMMENT ON TABLE jarvis_identity_evolution IS 'Audit trail of identity changes';
COMMENT ON TABLE jarvis_session_learnings IS 'End-of-session learning summaries';
