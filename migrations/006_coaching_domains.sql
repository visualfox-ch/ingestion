-- Migration: Coaching Domains & Learning System
-- Phase 1, 3, 5 of Multi-Domain Coach

-- User's active domain state
CREATE TABLE IF NOT EXISTS user_domain_state (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    active_domain VARCHAR(100) NOT NULL DEFAULT 'general',
    switched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uds_user ON user_domain_state(user_id);

-- Domain coaching sessions
CREATE TABLE IF NOT EXISTS domain_session (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'active',
    goals JSONB DEFAULT '[]',
    notes TEXT,
    progress_pct INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ds_user ON domain_session(user_id);
CREATE INDEX IF NOT EXISTS idx_ds_domain ON domain_session(domain_id);
CREATE INDEX IF NOT EXISTS idx_ds_status ON domain_session(status);

-- Domain-specific goals
CREATE TABLE IF NOT EXISTS domain_goal (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    goal_title TEXT NOT NULL,
    goal_description TEXT,
    target_date DATE,
    progress_pct INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    milestones JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dg_user_domain ON domain_goal(user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_dg_status ON domain_goal(status);

-- Cross-domain insights
CREATE TABLE IF NOT EXISTS cross_domain_insight (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source_domain VARCHAR(100) NOT NULL,
    target_domain VARCHAR(100),
    insight_type VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    evidence JSONB DEFAULT '[]',
    applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cdi_user ON cross_domain_insight(user_id);
CREATE INDEX IF NOT EXISTS idx_cdi_source ON cross_domain_insight(source_domain);
CREATE INDEX IF NOT EXISTS idx_cdi_applied ON cross_domain_insight(applied);

-- User competency tracking per domain
CREATE TABLE IF NOT EXISTS user_competency (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    competency_name VARCHAR(255) NOT NULL,
    current_level INTEGER DEFAULT 1,
    target_level INTEGER,
    evidence JSONB DEFAULT '[]',
    last_assessed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, domain_id, competency_name)
);

CREATE INDEX IF NOT EXISTS idx_uc_user_domain ON user_competency(user_id, domain_id);

-- Coaching effectiveness metrics
CREATE TABLE IF NOT EXISTS coaching_effectiveness (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    metric_type VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ce_user_domain ON coaching_effectiveness(user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_ce_type ON coaching_effectiveness(metric_type);
CREATE INDEX IF NOT EXISTS idx_ce_created ON coaching_effectiveness(created_at DESC);

-- Competency assessments (history)
CREATE TABLE IF NOT EXISTS competency_assessment (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100) NOT NULL,
    competency_name VARCHAR(255) NOT NULL,
    assessed_level INTEGER NOT NULL,
    evidence TEXT,
    assessed_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ca_user_domain ON competency_assessment(user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_ca_competency ON competency_assessment(competency_name);
CREATE INDEX IF NOT EXISTS idx_ca_created ON competency_assessment(created_at DESC);

-- Scheduled coaching interactions
CREATE TABLE IF NOT EXISTS scheduled_interaction (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    domain_id VARCHAR(100),
    interaction_type VARCHAR(100) NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    content JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    executed_at TIMESTAMPTZ,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_si_user ON scheduled_interaction(user_id);
CREATE INDEX IF NOT EXISTS idx_si_scheduled ON scheduled_interaction(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_si_status ON scheduled_interaction(status);

-- Learning digest (weekly summaries)
CREATE TABLE IF NOT EXISTS learning_digest (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    digest_type VARCHAR(50) DEFAULT 'weekly',
    content JSONB NOT NULL,
    delivered BOOLEAN DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ld_user ON learning_digest(user_id);
CREATE INDEX IF NOT EXISTS idx_ld_period ON learning_digest(period_start, period_end);
