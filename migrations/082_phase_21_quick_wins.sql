-- Phase 21 Quick Wins Migration
-- T-21A-01: Smart Tool Chains
-- T-21A-04: Tool Performance Learning
-- T-21B-01: CK-Track (Causal Knowledge)
-- T-21C-01: Agent State Persistence

-- ============================================
-- T-21A-01: Smart Tool Chains
-- Tracks which tools are used together in sessions
-- ============================================

CREATE TABLE IF NOT EXISTS jarvis_tool_chains (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tool_sequence JSONB NOT NULL DEFAULT '[]',  -- ["tool1", "tool2", "tool3"]
    query_context TEXT,  -- Original query that triggered this chain
    chain_success BOOLEAN DEFAULT TRUE,
    total_duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_chains_user ON jarvis_tool_chains(user_id);
CREATE INDEX IF NOT EXISTS idx_tool_chains_created ON jarvis_tool_chains(created_at);

-- Aggregated patterns (precomputed for fast lookup)
CREATE TABLE IF NOT EXISTS jarvis_tool_chain_patterns (
    id SERIAL PRIMARY KEY,
    pattern JSONB NOT NULL,  -- ["search_knowledge", "recall_conversation_history"]
    pattern_hash TEXT UNIQUE NOT NULL,  -- For deduplication
    occurrence_count INTEGER DEFAULT 1,
    avg_success_rate FLOAT DEFAULT 1.0,
    avg_duration_ms FLOAT,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_patterns_hash ON jarvis_tool_chain_patterns(pattern_hash);
CREATE INDEX IF NOT EXISTS idx_tool_patterns_count ON jarvis_tool_chain_patterns(occurrence_count DESC);

-- ============================================
-- T-21A-04: Tool Performance Learning
-- Tracks success/failure per tool with context
-- ============================================

CREATE TABLE IF NOT EXISTS jarvis_tool_performance (
    id SERIAL PRIMARY KEY,
    tool_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT,
    success BOOLEAN NOT NULL,
    error_type TEXT,  -- None if success, otherwise error category
    error_message TEXT,
    duration_ms INTEGER,
    input_tokens INTEGER,  -- Complexity indicator
    context_type TEXT,  -- "work", "personal", "technical", etc.
    time_of_day TEXT,  -- "morning", "afternoon", "evening", "night"
    day_of_week INTEGER,  -- 0=Monday, 6=Sunday
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_perf_tool ON jarvis_tool_performance(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_perf_user ON jarvis_tool_performance(user_id);
CREATE INDEX IF NOT EXISTS idx_tool_perf_success ON jarvis_tool_performance(success);
CREATE INDEX IF NOT EXISTS idx_tool_perf_created ON jarvis_tool_performance(created_at);

-- Aggregated stats per tool (updated periodically)
CREATE TABLE IF NOT EXISTS jarvis_tool_performance_stats (
    id SERIAL PRIMARY KEY,
    tool_name TEXT NOT NULL,
    user_id TEXT DEFAULT 'global',  -- 'global' for all users
    total_calls INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    success_rate FLOAT DEFAULT 1.0,
    avg_duration_ms FLOAT,
    p95_duration_ms FLOAT,
    best_time_of_day TEXT,  -- When this tool works best
    best_context_type TEXT,  -- In what context this tool works best
    last_failure_at TIMESTAMP WITH TIME ZONE,
    last_success_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tool_name, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_stats_tool ON jarvis_tool_performance_stats(tool_name);

-- ============================================
-- T-21B-01: CK-Track (Causal Knowledge)
-- "Wenn X, dann Y" patterns
-- ============================================

CREATE TABLE IF NOT EXISTS jarvis_causal_patterns (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    cause TEXT NOT NULL,  -- "late_night_work"
    effect TEXT NOT NULL,  -- "morning_coffee_needed"
    cause_type TEXT NOT NULL,  -- "behavior", "event", "state", "action"
    effect_type TEXT NOT NULL,  -- "need", "outcome", "state", "recommendation"
    confidence FLOAT DEFAULT 0.5,  -- 0.0 to 1.0
    evidence_count INTEGER DEFAULT 1,  -- How many times observed
    last_observed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    first_observed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',  -- Additional context
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_causal_user ON jarvis_causal_patterns(user_id);
CREATE INDEX IF NOT EXISTS idx_causal_cause ON jarvis_causal_patterns(cause);
CREATE INDEX IF NOT EXISTS idx_causal_effect ON jarvis_causal_patterns(effect);
CREATE INDEX IF NOT EXISTS idx_causal_confidence ON jarvis_causal_patterns(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_causal_active ON jarvis_causal_patterns(active) WHERE active = TRUE;

-- Observations that led to patterns
CREATE TABLE IF NOT EXISTS jarvis_causal_observations (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    pattern_id INTEGER REFERENCES jarvis_causal_patterns(id) ON DELETE SET NULL,
    cause_event TEXT NOT NULL,
    effect_event TEXT NOT NULL,
    time_delta_minutes INTEGER,  -- Time between cause and effect
    session_id TEXT,
    context JSONB DEFAULT '{}',
    observed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_causal_obs_pattern ON jarvis_causal_observations(pattern_id);
CREATE INDEX IF NOT EXISTS idx_causal_obs_user ON jarvis_causal_observations(user_id);

-- ============================================
-- T-21C-01: Agent State Persistence
-- State for AI agents (Claude Code, Copilot, Codex)
-- ============================================

CREATE TABLE IF NOT EXISTS jarvis_agent_state (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,  -- "claude_code", "copilot", "codex"
    user_id TEXT NOT NULL,
    state_key TEXT NOT NULL,  -- What aspect of state
    state_value JSONB NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,  -- NULL = never expires
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(agent_id, user_id, state_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_state_agent ON jarvis_agent_state(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_state_user ON jarvis_agent_state(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_state_key ON jarvis_agent_state(state_key);
CREATE INDEX IF NOT EXISTS idx_agent_state_expires ON jarvis_agent_state(expires_at) WHERE expires_at IS NOT NULL;

-- Agent session history (what each agent worked on)
CREATE TABLE IF NOT EXISTS jarvis_agent_sessions (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    working_directory TEXT,
    files_modified JSONB DEFAULT '[]',
    tasks_completed JSONB DEFAULT '[]',
    tools_used JSONB DEFAULT '[]',
    summary TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_minutes INTEGER,
    success BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent ON jarvis_agent_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_user ON jarvis_agent_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_started ON jarvis_agent_sessions(started_at DESC);

-- Cross-agent handoffs (when one agent passes work to another)
CREATE TABLE IF NOT EXISTS jarvis_agent_handoffs (
    id SERIAL PRIMARY KEY,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    user_id TEXT NOT NULL,
    context JSONB NOT NULL,  -- What was passed
    files_involved JSONB DEFAULT '[]',
    reason TEXT,
    status TEXT DEFAULT 'pending',  -- "pending", "accepted", "completed", "rejected"
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_handoffs_from ON jarvis_agent_handoffs(from_agent);
CREATE INDEX IF NOT EXISTS idx_handoffs_to ON jarvis_agent_handoffs(to_agent);
CREATE INDEX IF NOT EXISTS idx_handoffs_status ON jarvis_agent_handoffs(status);

-- Migration marker
INSERT INTO jarvis_migrations (name, applied_at)
VALUES ('082_phase_21_quick_wins', NOW())
ON CONFLICT (name) DO NOTHING;
