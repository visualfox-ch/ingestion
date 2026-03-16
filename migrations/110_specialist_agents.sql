-- Migration 110: Specialist Agent System (Tier 3 #8)
-- Creates infrastructure for domain-specific specialist agents:
-- FitJarvis, WorkJarvis, CommJarvis

-- Specialist definitions
CREATE TABLE IF NOT EXISTS jarvis_specialists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,           -- 'fit', 'work', 'comm'
    display_name VARCHAR(100) NOT NULL,          -- 'FitJarvis', 'WorkJarvis'
    description TEXT,

    -- Detection
    keywords JSONB DEFAULT '[]'::jsonb,          -- Trigger keywords
    domains JSONB DEFAULT '[]'::jsonb,           -- Related domains

    -- Persona configuration
    persona_prompt TEXT,                          -- System prompt addon
    tone VARCHAR(50) DEFAULT 'friendly',          -- friendly, professional, coach
    emoji_level VARCHAR(20) DEFAULT 'moderate',   -- none, minimal, moderate, heavy
    verbosity VARCHAR(20) DEFAULT 'concise',      -- terse, concise, detailed

    -- Tool configuration
    preferred_tools JSONB DEFAULT '[]'::jsonb,    -- Tools to prioritize
    excluded_tools JSONB DEFAULT '[]'::jsonb,     -- Tools to avoid
    tool_weights JSONB DEFAULT '{}'::jsonb,       -- Tool priority weights

    -- Context configuration
    context_injections JSONB DEFAULT '[]'::jsonb, -- Extra context types to inject
    knowledge_domains JSONB DEFAULT '[]'::jsonb,  -- Knowledge domains to query

    -- Model preferences
    preferred_model VARCHAR(100),                 -- Preferred LLM model
    fallback_model VARCHAR(100),                  -- Fallback model
    max_tokens INTEGER DEFAULT 2000,

    -- Behavior
    proactive_hints BOOLEAN DEFAULT TRUE,         -- Give unsolicited advice
    remember_context BOOLEAN DEFAULT TRUE,        -- Cross-session memory

    -- Status
    enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,                 -- Lower = higher priority

    -- Metrics
    activation_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.5,
    avg_satisfaction REAL,
    last_activated_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Specialist activation history
CREATE TABLE IF NOT EXISTS jarvis_specialist_activations (
    id SERIAL PRIMARY KEY,
    specialist_id INTEGER REFERENCES jarvis_specialists(id),
    specialist_name VARCHAR(50) NOT NULL,

    -- Activation context
    session_id VARCHAR(100),
    query_hash VARCHAR(32),
    trigger_type VARCHAR(50),                     -- keyword, domain, explicit, context
    trigger_value TEXT,                           -- What triggered activation
    confidence REAL DEFAULT 1.0,

    -- Execution
    tools_used JSONB DEFAULT '[]'::jsonb,
    tokens_used INTEGER,
    duration_ms INTEGER,

    -- Outcome
    success BOOLEAN,
    user_feedback VARCHAR(20),                    -- positive, neutral, negative

    created_at TIMESTAMP DEFAULT NOW()
);

-- Specialist-specific knowledge
CREATE TABLE IF NOT EXISTS jarvis_specialist_knowledge (
    id SERIAL PRIMARY KEY,
    specialist_id INTEGER REFERENCES jarvis_specialists(id),
    specialist_name VARCHAR(50) NOT NULL,

    -- Knowledge entry
    topic VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    content_type VARCHAR(50) DEFAULT 'fact',      -- fact, rule, preference, example

    -- Relevance
    keywords JSONB DEFAULT '[]'::jsonb,
    priority INTEGER DEFAULT 100,

    -- Usage tracking
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    -- Status
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Specialist context memory (cross-session)
CREATE TABLE IF NOT EXISTS jarvis_specialist_memory (
    id SERIAL PRIMARY KEY,
    specialist_id INTEGER REFERENCES jarvis_specialists(id),
    specialist_name VARCHAR(50) NOT NULL,

    -- Memory content
    memory_type VARCHAR(50) NOT NULL,             -- goal, preference, pattern, fact
    key VARCHAR(200) NOT NULL,
    value JSONB NOT NULL,

    -- Context
    related_session_id VARCHAR(100),
    confidence REAL DEFAULT 0.8,

    -- Lifecycle
    expires_at TIMESTAMP,                         -- NULL = permanent
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(specialist_name, memory_type, key)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_specialists_enabled ON jarvis_specialists(enabled, priority);
CREATE INDEX IF NOT EXISTS idx_specialists_keywords ON jarvis_specialists USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_specialist_activations_specialist ON jarvis_specialist_activations(specialist_id);
CREATE INDEX IF NOT EXISTS idx_specialist_activations_session ON jarvis_specialist_activations(session_id);
CREATE INDEX IF NOT EXISTS idx_specialist_knowledge_specialist ON jarvis_specialist_knowledge(specialist_id);
CREATE INDEX IF NOT EXISTS idx_specialist_knowledge_keywords ON jarvis_specialist_knowledge USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_specialist_memory_specialist ON jarvis_specialist_memory(specialist_name, memory_type);

-- Seed initial specialists
INSERT INTO jarvis_specialists (name, display_name, description, keywords, domains, persona_prompt, tone, preferred_tools, knowledge_domains, proactive_hints)
VALUES
(
    'fit',
    'FitJarvis',
    'Fitness, Gesundheit, Ernährung und Wellness Specialist. Unterstützt bei Sport, Gewichtsziele, Schlaf und körperlichem Wohlbefinden.',
    '["fitness", "sport", "training", "workout", "gym", "laufen", "joggen", "gewicht", "abnehmen", "zunehmen", "kalorien", "ernährung", "essen", "protein", "schlaf", "müde", "energie", "gesundheit", "körper", "muskeln", "cardio", "kraft", "dehnen", "yoga", "meditation", "stress", "erholung", "regeneration"]'::jsonb,
    '["fitness", "health", "nutrition", "wellness"]'::jsonb,
    'Du bist FitJarvis - Michas persönlicher Fitness & Wellness Coach.
Dein Fokus: Praktische, umsetzbare Tipps für Fitness, Ernährung und Wohlbefinden.
Stil: Motivierend aber realistisch. Keine unrealistischen Versprechen.
Wichtig:
- Kenne Michas Ziele und Fortschritte
- Erinnere an vergangene Erfolge zur Motivation
- Schlage konkrete nächste Schritte vor
- Berücksichtige Tageszeit und Energielevel',
    'coach',
    '["get_goal_status", "record_goal_progress", "get_active_goals", "create_goal", "calendar_create_event", "create_reminder"]'::jsonb,
    '["fitness", "health", "personal"]'::jsonb,
    TRUE
),
(
    'work',
    'WorkJarvis',
    'Produktivität, Projekte und berufliche Aufgaben Specialist. Unterstützt bei Task-Management, Zeitplanung und professioneller Kommunikation.',
    '["arbeit", "work", "projekt", "project", "task", "aufgabe", "deadline", "meeting", "email", "präsentation", "report", "bericht", "kunde", "client", "team", "kollege", "chef", "büro", "office", "produktiv", "fokus", "priorisierung", "zeitplan", "schedule", "asana", "jira", "todo", "erledigen", "agenda", "call"]'::jsonb,
    '["work", "productivity", "professional"]'::jsonb,
    'Du bist WorkJarvis - Michas professioneller Produktivitäts-Partner.
Dein Fokus: Effiziente Aufgabenbearbeitung, klare Priorisierung, professionelle Kommunikation.
Stil: Strukturiert, effizient, lösungsorientiert.
Wichtig:
- Kenne aktuelle Projekte und Deadlines
- Hilf bei Priorisierung (Eisenhower-Matrix Denken)
- Schlage Zeitblöcke und Fokus-Sessions vor
- Unterstütze bei professioneller Kommunikation
- Vermeide Scope Creep',
    'professional',
    '["get_asana_tasks", "update_asana_task", "create_asana_task", "calendar_create_event", "calendar_get_events", "send_email_via_n8n", "create_reminder", "get_active_goals"]'::jsonb,
    '["work", "productivity", "professional"]'::jsonb,
    TRUE
),
(
    'comm',
    'CommJarvis',
    'Kommunikation und Beziehungs-Specialist. Unterstützt bei Nachrichten, Social Media, Networking und zwischenmenschlicher Kommunikation.',
    '["nachricht", "message", "whatsapp", "telegram", "sms", "antwort", "reply", "email", "linkedin", "social", "netzwerk", "kontakt", "freund", "familie", "beziehung", "geburtstag", "gratulation", "danke", "entschuldigung", "einladung", "absage", "zusage", "kommentar", "post", "content", "kommunikation", "formulierung", "ton"]'::jsonb,
    '["communication", "social", "relationships"]'::jsonb,
    'Du bist CommJarvis - Michas Kommunikations-Berater.
Dein Fokus: Authentische, effektive Kommunikation die Michas Stil trifft.
Stil: Empathisch, nuanciert, kulturell bewusst.
Wichtig:
- Kenne Michas Kommunikationsstil und Präferenzen
- Berücksichtige Kontext und Beziehung zum Empfänger
- Schlage verschiedene Formulierungsoptionen vor
- Hilf bei Timing (wann ist der beste Moment)
- Nutze Playbooks für konsistenten Stil',
    'friendly',
    '["get_playbook", "list_playbooks", "send_telegram_message", "send_email_via_n8n", "linkedin_comment_coach", "get_entity_context"]'::jsonb,
    '["communication", "social", "relationships"]'::jsonb,
    TRUE
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    keywords = EXCLUDED.keywords,
    domains = EXCLUDED.domains,
    persona_prompt = EXCLUDED.persona_prompt,
    tone = EXCLUDED.tone,
    preferred_tools = EXCLUDED.preferred_tools,
    knowledge_domains = EXCLUDED.knowledge_domains,
    updated_at = NOW();

-- Add some initial specialist knowledge
INSERT INTO jarvis_specialist_knowledge (specialist_name, topic, content, content_type, keywords, priority)
VALUES
-- FitJarvis knowledge
('fit', 'Michas Fitness-Ziel', 'Micha möchte fitter werden und hat ein Ziel von 5kg Gewichtsverlust. Bevorzugt Laufen und Home-Workouts.', 'fact', '["fitness", "ziel", "gewicht"]'::jsonb, 10),
('fit', 'Trainings-Timing', 'Micha trainiert am liebsten morgens vor der Arbeit oder abends nach 18 Uhr. Mittagstraining ist schwierig wegen Meetings.', 'preference', '["training", "zeit", "schedule"]'::jsonb, 20),
('fit', 'Ernährungspräferenz', 'Micha isst flexitarisch, kein striktes Diet. Mag einfache, schnelle Mahlzeiten. Protein-Fokus ist wichtig.', 'preference', '["ernährung", "essen", "protein"]'::jsonb, 20),

-- WorkJarvis knowledge
('work', 'Arbeitsweise', 'Micha arbeitet remote, nutzt Asana für Tasks, Google Calendar für Termine. Beste Fokuszeit: Vormittags 9-12 Uhr.', 'fact', '["arbeit", "produktivität", "tools"]'::jsonb, 10),
('work', 'Meeting-Präferenzen', 'Micha bevorzugt kurze Meetings (max 30min), async Kommunikation über Slack, und meeting-freie Freitag-Nachmittage.', 'preference', '["meeting", "kommunikation", "zeit"]'::jsonb, 20),
('work', 'Priorisierungs-Regel', 'Bei Überlastung: Erst Kunden-Deadlines, dann interne Projekte, dann Nice-to-haves. Im Zweifel nachfragen statt raten.', 'rule', '["priorität", "deadline", "entscheidung"]'::jsonb, 10),

-- CommJarvis knowledge
('comm', 'Kommunikationsstil', 'Micha kommuniziert direkt aber freundlich. Nutzt wenig Emojis beruflich, mehr privat. Duzt fast immer.', 'fact', '["stil", "ton", "emojis"]'::jsonb, 10),
('comm', 'LinkedIn Aktivität', 'Micha ist auf LinkedIn aktiv, kommentiert gerne zu Tech/KI/Produktivitäts-Themen. Nutzt Playbook für konsistenten Stil.', 'fact', '["linkedin", "social", "content"]'::jsonb, 20),
('comm', 'Wichtige Kontakte', 'Familie und enge Freunde haben Priorität. Bei Geburtstagen und wichtigen Events proaktiv erinnern.', 'rule', '["kontakte", "beziehungen", "reminder"]'::jsonb, 10)
ON CONFLICT DO NOTHING;

COMMENT ON TABLE jarvis_specialists IS 'Domain-specific specialist agent definitions (Tier 3 #8)';
COMMENT ON TABLE jarvis_specialist_activations IS 'Tracks when and why specialists were activated';
COMMENT ON TABLE jarvis_specialist_knowledge IS 'Specialist-specific knowledge entries';
COMMENT ON TABLE jarvis_specialist_memory IS 'Cross-session memory per specialist';
