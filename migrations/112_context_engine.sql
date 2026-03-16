-- Migration 112: Context Engine (Tier 3 #10)
-- Aggregates multiple context signals for mood-aware responses
-- "Stressed" → different tools/tone than "Relaxed"

-- Context signals - individual signal readings
CREATE TABLE IF NOT EXISTS jarvis_context_signals (
    id SERIAL PRIMARY KEY,
    signal_type VARCHAR(50) NOT NULL,          -- emotion, time, calendar, energy, activity
    signal_value VARCHAR(100) NOT NULL,         -- e.g., "stressed", "morning", "busy"
    intensity REAL DEFAULT 0.5,                 -- 0.0 to 1.0

    -- Source
    user_id VARCHAR(50),
    session_id VARCHAR(100),
    source VARCHAR(50),                         -- auto_detect, user_input, calendar, system

    -- Metadata
    raw_data JSONB,                             -- Original data that produced signal
    confidence REAL DEFAULT 0.8,

    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP                        -- Some signals are time-limited
);

-- Context profiles - aggregated context state
CREATE TABLE IF NOT EXISTS jarvis_context_profiles (
    id SERIAL PRIMARY KEY,
    profile_id VARCHAR(50) NOT NULL UNIQUE,     -- UUID or session-based

    -- Aggregated state
    primary_mood VARCHAR(50),                   -- calm, stressed, energized, tired, focused
    energy_level REAL,                          -- 0.0 (exhausted) to 1.0 (high energy)
    stress_level REAL,                          -- 0.0 (relaxed) to 1.0 (very stressed)
    focus_level REAL,                           -- 0.0 (scattered) to 1.0 (deep focus)

    -- Time context
    time_of_day VARCHAR(20),                    -- morning, afternoon, evening, night
    day_type VARCHAR(20),                       -- workday, weekend, holiday

    -- Load indicators
    calendar_load VARCHAR(20),                  -- free, light, moderate, busy, packed
    task_load VARCHAR(20),                      -- low, normal, high, overwhelming

    -- Derived recommendations
    recommended_tone VARCHAR(30),               -- supportive, efficient, energetic, calm
    recommended_verbosity VARCHAR(20),          -- terse, concise, detailed
    tool_priority_adjustments JSONB,            -- {"fitness": -0.2, "calendar": +0.3}

    -- Context
    user_id VARCHAR(50),
    session_id VARCHAR(100),
    signals_used JSONB DEFAULT '[]'::jsonb,     -- IDs of signals that contributed

    -- Lifecycle
    valid_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Context rules - how to respond to different contexts
CREATE TABLE IF NOT EXISTS jarvis_context_rules (
    id SERIAL PRIMARY KEY,
    rule_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,

    -- Conditions (all must match)
    conditions JSONB NOT NULL,                  -- {"mood": "stressed", "energy_level": {"lt": 0.4}}

    -- Actions
    tone_adjustment VARCHAR(30),                -- Override tone
    verbosity_adjustment VARCHAR(20),           -- Override verbosity
    tool_adjustments JSONB,                     -- Tool priority changes
    prompt_injection TEXT,                      -- Extra prompt to inject
    specialist_preference VARCHAR(20),          -- Prefer specific specialist

    -- Status
    enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,               -- Lower = higher priority

    -- Stats
    trigger_count INTEGER DEFAULT 0,
    last_triggered_at TIMESTAMP,
    effectiveness_score REAL,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Context history - for learning patterns
CREATE TABLE IF NOT EXISTS jarvis_context_history (
    id SERIAL PRIMARY KEY,
    profile_id VARCHAR(50) NOT NULL,

    -- Snapshot
    mood VARCHAR(50),
    energy_level REAL,
    stress_level REAL,
    time_of_day VARCHAR(20),
    day_of_week INTEGER,                        -- 0-6
    hour_of_day INTEGER,                        -- 0-23

    -- Outcome
    rules_applied JSONB DEFAULT '[]'::jsonb,
    response_quality REAL,                      -- User feedback score

    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_context_signals_type ON jarvis_context_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_context_signals_session ON jarvis_context_signals(session_id);
CREATE INDEX IF NOT EXISTS idx_context_signals_created ON jarvis_context_signals(created_at);
CREATE INDEX IF NOT EXISTS idx_context_profiles_session ON jarvis_context_profiles(session_id);
CREATE INDEX IF NOT EXISTS idx_context_profiles_user ON jarvis_context_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_context_rules_enabled ON jarvis_context_rules(enabled, priority);
CREATE INDEX IF NOT EXISTS idx_context_history_time ON jarvis_context_history(created_at);

-- Seed default context rules
INSERT INTO jarvis_context_rules (rule_name, description, conditions, tone_adjustment, verbosity_adjustment, tool_adjustments, prompt_injection, specialist_preference, priority)
VALUES
(
    'stressed_user',
    'User is stressed - be supportive and efficient',
    '{"stress_level": {"gte": 0.7}}'::jsonb,
    'supportive',
    'concise',
    '{"calendar_create_event": -0.3, "get_asana_tasks": -0.2}'::jsonb,
    'Der User ist gestresst. Sei besonders einfühlsam, schlage nicht zu viele neue Aufgaben vor, und biete wenn möglich Entlastung an.',
    NULL,
    10
),
(
    'low_energy',
    'User has low energy - keep it simple',
    '{"energy_level": {"lt": 0.3}}'::jsonb,
    'calm',
    'terse',
    '{"fitness": -0.2}'::jsonb,
    'Der User hat wenig Energie. Halte Antworten kurz, vermeide überwältigende Informationen.',
    NULL,
    20
),
(
    'high_energy_morning',
    'Energized morning - good for challenging tasks',
    '{"energy_level": {"gte": 0.7}, "time_of_day": "morning"}'::jsonb,
    'energetic',
    'detailed',
    '{"fitness": 0.2, "get_active_goals": 0.3}'::jsonb,
    'Der User ist energiegeladen am Morgen. Guter Zeitpunkt für anspruchsvolle Aufgaben oder Fitness.',
    'fit',
    30
),
(
    'busy_workday',
    'Heavy calendar load - be efficient',
    '{"calendar_load": "packed", "day_type": "workday"}'::jsonb,
    'efficient',
    'terse',
    '{"calendar_get_events": 0.3, "get_asana_tasks": 0.2}'::jsonb,
    'Der User hat einen vollen Kalender. Antworte effizient und fokussiert auf Wesentliches.',
    'work',
    25
),
(
    'relaxed_evening',
    'Calm evening - open for reflection',
    '{"stress_level": {"lt": 0.3}, "time_of_day": "evening"}'::jsonb,
    'friendly',
    'detailed',
    '{"recall_facts": 0.2}'::jsonb,
    'Entspannter Abend. Zeit für Reflexion oder entspannte Gespräche.',
    NULL,
    40
),
(
    'weekend_mode',
    'Weekend - more casual tone',
    '{"day_type": "weekend"}'::jsonb,
    'casual',
    'concise',
    '{"get_asana_tasks": -0.3, "fitness": 0.1}'::jsonb,
    'Wochenende - lockerer Ton, weniger Arbeitsfokus.',
    NULL,
    50
),
(
    'overwhelmed_user',
    'User is overwhelmed - maximum support',
    '{"mood": "overwhelmed"}'::jsonb,
    'supportive',
    'terse',
    '{"create_asana_task": -0.5, "calendar_create_event": -0.5}'::jsonb,
    'WICHTIG: Der User ist überlastet. Keine neuen Aufgaben vorschlagen! Hilf beim Priorisieren und Entlasten. Frage: "Was können wir streichen oder verschieben?"',
    NULL,
    5
)
ON CONFLICT (rule_name) DO UPDATE SET
    description = EXCLUDED.description,
    conditions = EXCLUDED.conditions,
    tone_adjustment = EXCLUDED.tone_adjustment,
    verbosity_adjustment = EXCLUDED.verbosity_adjustment,
    tool_adjustments = EXCLUDED.tool_adjustments,
    prompt_injection = EXCLUDED.prompt_injection;

COMMENT ON TABLE jarvis_context_signals IS 'Individual context signal readings (Tier 3 #10)';
COMMENT ON TABLE jarvis_context_profiles IS 'Aggregated context state for a session';
COMMENT ON TABLE jarvis_context_rules IS 'Rules for context-aware response adjustments';
COMMENT ON TABLE jarvis_context_history IS 'Historical context data for pattern learning';
