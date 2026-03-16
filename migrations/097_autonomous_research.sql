-- Migration: 097_autonomous_research.sql
-- Purpose: Autonomous research orchestration tables
-- Date: 2026-03-14

-- Research schedule configuration
CREATE TABLE IF NOT EXISTS research_schedule (
    id SERIAL PRIMARY KEY,
    domain_id INTEGER REFERENCES research_domains(id),
    schedule_type VARCHAR(50) NOT NULL,  -- daily, weekly, on_demand
    schedule_config JSONB NOT NULL,       -- {"hour": 18, "minute": 0, "days": ["mon", "wed", "fri"]}
    max_topics_per_run INTEGER DEFAULT 3,
    priority INTEGER DEFAULT 5,
    is_enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Research run history
CREATE TABLE IF NOT EXISTS research_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) UNIQUE NOT NULL,
    domain_id INTEGER REFERENCES research_domains(id),
    triggered_by VARCHAR(50) NOT NULL,  -- scheduler, manual, proactive
    status VARCHAR(50) DEFAULT 'running',
    topics_processed INTEGER DEFAULT 0,
    results_created INTEGER DEFAULT 0,
    insights_generated INTEGER DEFAULT 0,
    errors JSONB,
    tokens_used INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Research insights (actionable findings)
CREATE TABLE IF NOT EXISTS research_insights (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) REFERENCES research_runs(run_id),
    topic_id INTEGER,
    insight_type VARCHAR(50) NOT NULL,  -- trend, opportunity, risk, news, learning
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.7,
    relevance_score FLOAT DEFAULT 0.5,
    source_urls TEXT[],
    tags TEXT[],
    is_notified BOOLEAN DEFAULT FALSE,
    is_actioned BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Research topic priorities (dynamic)
CREATE TABLE IF NOT EXISTS research_topic_priorities (
    id SERIAL PRIMARY KEY,
    topic_id INTEGER REFERENCES research_topics(id),
    priority_score FLOAT DEFAULT 0.5,
    last_researched_at TIMESTAMP,
    research_count INTEGER DEFAULT 0,
    success_rate FLOAT DEFAULT 1.0,
    avg_insights_per_run FLOAT DEFAULT 0.0,
    user_interest_score FLOAT DEFAULT 0.5,  -- based on queries/interactions
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(topic_id)
);

-- User research interests (learned from interactions)
CREATE TABLE IF NOT EXISTS research_user_interests (
    id SERIAL PRIMARY KEY,
    interest_topic VARCHAR(255) NOT NULL,
    interest_keywords TEXT[],
    mention_count INTEGER DEFAULT 1,
    last_mentioned_at TIMESTAMP DEFAULT NOW(),
    confidence FLOAT DEFAULT 0.5,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert default schedule for existing domains
INSERT INTO research_schedule (domain_id, schedule_type, schedule_config, max_topics_per_run, priority)
SELECT
    id,
    'daily',
    '{"hour": 18, "minute": 0}'::jsonb,
    3,
    priority
FROM research_domains
WHERE is_active = TRUE
ON CONFLICT DO NOTHING;

-- Initialize topic priorities for existing topics
INSERT INTO research_topic_priorities (topic_id, priority_score)
SELECT id, 0.5
FROM research_topics
WHERE is_active = TRUE
ON CONFLICT (topic_id) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_research_schedule_next_run ON research_schedule(next_run_at);
CREATE INDEX IF NOT EXISTS idx_research_runs_started ON research_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status);
CREATE INDEX IF NOT EXISTS idx_research_insights_created ON research_insights(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_insights_type ON research_insights(insight_type);
CREATE INDEX IF NOT EXISTS idx_research_insights_notified ON research_insights(is_notified) WHERE is_notified = FALSE;
CREATE INDEX IF NOT EXISTS idx_research_topic_priorities_score ON research_topic_priorities(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_research_user_interests_active ON research_user_interests(is_active, confidence DESC);

-- Add autonomous_research tool
INSERT INTO jarvis_tools (name, description, category, is_enabled, requires_approval, parameters, keywords) VALUES
    ('run_autonomous_research', 'Execute autonomous research on high-priority topics', 'research', TRUE, TRUE,
     '{"domain": "optional string", "max_topics": "optional int"}',
     ARRAY['research', 'recherche', 'autonom', 'hintergrund', 'background'])
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    requires_approval = EXCLUDED.requires_approval;
