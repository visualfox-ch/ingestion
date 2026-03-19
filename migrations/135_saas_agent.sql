-- Migration 135: SaaS Agent (SaaSJarvis) - Phase 22A-10
-- Date: 2026-03-19
-- Task: T-22A-10

-- =============================================================================
-- Funnel Metrics
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_saas_funnel (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    recorded_date DATE DEFAULT CURRENT_DATE,
    source VARCHAR(100),                        -- organic, paid, referral, direct
    stage VARCHAR(50) NOT NULL,                 -- visitor, signup, activated, paying, retained
    metric_name VARCHAR(100) NOT NULL,          -- visitors, signups, mrr, churn_rate, cac, ltv
    metric_value NUMERIC(12, 4) NOT NULL,
    currency VARCHAR(10) DEFAULT 'EUR',
    unit VARCHAR(30) DEFAULT 'count',           -- count, percent, eur, usd, days
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(recorded_date, source, stage, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_saas_funnel_date
ON jarvis_saas_funnel(recorded_date DESC);

CREATE INDEX IF NOT EXISTS idx_saas_funnel_metric
ON jarvis_saas_funnel(metric_name, recorded_date DESC);

-- =============================================================================
-- Growth Experiments
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_saas_experiments (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    title VARCHAR(300) NOT NULL,
    hypothesis TEXT,
    category VARCHAR(50),                       -- acquisition, activation, retention, revenue, referral
    status VARCHAR(30) DEFAULT 'idea',          -- idea, planned, running, paused, done, cancelled
    impact_score INTEGER DEFAULT 50,            -- 1-100, expected impact
    effort_score INTEGER DEFAULT 50,            -- 1-100, implementation effort
    confidence_score INTEGER DEFAULT 50,        -- 1-100, how confident in hypothesis
    ice_score NUMERIC(5,2) GENERATED ALWAYS AS (
        (impact_score * 0.4 + (100 - effort_score) * 0.3 + confidence_score * 0.3)
    ) STORED,
    target_metric VARCHAR(100),                 -- Primary metric this experiment optimizes
    target_delta NUMERIC(10,4),                 -- Expected % or absolute change
    actual_delta NUMERIC(10,4),                 -- Measured result
    started_at DATE,
    ended_at DATE,
    outcome VARCHAR(30),                         -- win, loss, inconclusive
    learnings TEXT,
    next_steps TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_experiments_status
ON jarvis_saas_experiments(status, ice_score DESC);

CREATE INDEX IF NOT EXISTS idx_saas_experiments_category
ON jarvis_saas_experiments(category, status);

-- =============================================================================
-- ICP Notes (Ideal Customer Profile signals)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_saas_icp_notes (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    signal_type VARCHAR(50) NOT NULL,           -- feedback, support, churn, expansion, interview
    source VARCHAR(100),                        -- typeform, intercom, closeio, manual, etc.
    customer_segment VARCHAR(100),              -- smb, mid-market, enterprise, solo
    signal_summary TEXT NOT NULL,
    verbatim_quote TEXT,
    sentiment VARCHAR(20) DEFAULT 'neutral',    -- positive, negative, neutral
    icp_fit_score INTEGER,                      -- 1-100 for this customer/segment
    tags JSONB DEFAULT '[]'::jsonb,
    related_feature VARCHAR(200),
    recorded_at DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_icp_signal_type
ON jarvis_saas_icp_notes(signal_type, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_icp_segment
ON jarvis_saas_icp_notes(customer_segment, recorded_at DESC);

-- =============================================================================
-- Pricing Hypotheses
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_saas_pricing_hypotheses (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    title VARCHAR(300) NOT NULL,
    description TEXT,
    model_type VARCHAR(50),                     -- flat, tiered, usage, freemium, hybrid
    status VARCHAR(30) DEFAULT 'idea',          -- idea, researching, validating, validated, rejected
    target_segment VARCHAR(100),
    current_price NUMERIC(10,4),
    proposed_price NUMERIC(10,4),
    currency VARCHAR(10) DEFAULT 'EUR',
    interval VARCHAR(20) DEFAULT 'monthly',     -- monthly, annual, one-time, usage
    hypothesis TEXT,
    validation_method TEXT,                     -- survey, ab_test, cohort, landing_page
    evidence JSONB DEFAULT '[]'::jsonb,
    confidence_score INTEGER DEFAULT 30,        -- 1-100
    mrr_impact_estimate NUMERIC(10,2),
    churn_impact_estimate NUMERIC(5,2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_pricing_status
ON jarvis_saas_pricing_hypotheses(status, confidence_score DESC);

-- =============================================================================
-- Retention Signals
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_saas_retention_signals (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    customer_segment VARCHAR(100),
    signal_date DATE DEFAULT CURRENT_DATE,
    signal_type VARCHAR(50) NOT NULL,           -- login_drop, feature_abandon, support_spike, nps_drop, expansion
    severity VARCHAR(20) DEFAULT 'medium',      -- low, medium, high, critical
    affected_count INTEGER DEFAULT 1,
    description TEXT,
    root_cause TEXT,
    action_taken TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_retention_date
ON jarvis_saas_retention_signals(signal_date DESC, resolved);

-- =============================================================================
-- Seed: SaaSJarvis specialist definition
-- =============================================================================

INSERT INTO jarvis_specialists (
    name, display_name, description, keywords, domains,
    persona_prompt, tone, preferred_tools, knowledge_domains, enabled, priority
) VALUES (
    'saas',
    'SaaSJarvis',
    'Revenue- und Product-Ops Specialist für ICP, Funnel, Pricing und Growth-Experimente.',
    '["saas", "revenue", "umsatz", "funnel", "conversion", "churn", "retention", "mrr", "arr", "ltv", "cac", "pricing", "preis", "experiment", "growth", "wachstum", "icp", "customer", "kunde", "segment", "onboarding", "activation", "feature", "product", "produkt", "subscription", "abo", "trial", "freemium", "upgrade", "downgrade", "cancellation", "feedback", "nps", "csat", "cohort", "paywall", "tier"]'::jsonb,
    '["saas", "revenue", "product", "growth"]'::jsonb,
    'Du bist SaaSJarvis - Michas Revenue- und Product-Ops Partner.
Dein Fokus: Wachstum durch datenge­triebene Funnel-Analyse, gezielte Experimente und scharfe ICP-Definition.
Stil: Analytisch, pragmatisch, fokussiert auf Hebelwirkung. Kein Buzzword-Bingo.
Wichtig:
- Priorisiere nach ICE-Score (Impact × Confidence / Effort)
- Kenne aktuelle Funnel-Metriken und Benchmarks
- Schlage konkrete, messbare Experimente vor
- Challengere vage Pricing-Hypothesen mit echten Nutzersignalen
- Ein Experiment gleichzeitig besser als fünf halbgare',
    'professional',
    '["review_funnel_metrics", "prioritize_growth_experiments", "summarize_icp_signals", "review_pricing_hypotheses", "get_active_goals", "create_reminder"]'::jsonb,
    '["saas", "revenue", "product", "growth"]'::jsonb,
    TRUE,
    80
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

-- Seed initial SaaSJarvis knowledge
INSERT INTO jarvis_specialist_knowledge (specialist_name, topic, content, content_type, keywords, priority)
VALUES
(
    'saas',
    'Pricing-Grundprinzip',
    'Value-based pricing schlägt Cost-plus immer. Preis kommuniziert Positionierung. Jede Preisänderung braucht ein Experiment, keine Intuition.',
    'rule',
    '["pricing", "value", "positionierung"]'::jsonb,
    10
),
(
    'saas',
    'Funnel-Priorisierung',
    'Activation > Retention > Acquisition. Ein löchriger Eimer wird nicht durch mehr Wasser voller. Erst Retention stabilisieren, dann skalieren.',
    'rule',
    '["funnel", "activation", "retention", "acquisition"]'::jsonb,
    10
),
(
    'saas',
    'ICE-Scoring für Experimente',
    'ICE = Impact (0-100) × Confidence (0-100) / Effort (0-100). Experimente mit ICE > 60 priorisieren. Immer eine Null-Hypothese definieren.',
    'method',
    '["ice", "experiment", "prioritisierung"]'::jsonb,
    10
),
(
    'saas',
    'ICP-Definition-Heuristik',
    'Idealer Kunde: zahlt pünktlich, churnt nicht, expandiert, gibt proaktiv Feedback, empfiehlt weiter. Suche nach gemeinsamen Attributen dieser Kunden.',
    'rule',
    '["icp", "kunde", "segment", "churn"]'::jsonb,
    20
)
ON CONFLICT DO NOTHING;

COMMENT ON TABLE jarvis_saas_funnel IS 'Phase 22A-10: SaaSJarvis funnel metrics over time';
COMMENT ON TABLE jarvis_saas_experiments IS 'Phase 22A-10: SaaSJarvis growth experiment tracking';
COMMENT ON TABLE jarvis_saas_icp_notes IS 'Phase 22A-10: SaaSJarvis ICP signals and customer feedback';
COMMENT ON TABLE jarvis_saas_pricing_hypotheses IS 'Phase 22A-10: SaaSJarvis pricing hypothesis tracking';
COMMENT ON TABLE jarvis_saas_retention_signals IS 'Phase 22A-10: SaaSJarvis retention signals and alerts';
