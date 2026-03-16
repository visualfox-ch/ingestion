-- Migration: 098_tool_usage_analytics.sql
-- Purpose: Context-Pattern Memory System Phase 1.1 - Tool Usage Analytics
-- Date: 2026-03-14

-- Context → Tool mapping (learned from usage patterns)
CREATE TABLE IF NOT EXISTS context_tool_mapping (
    id SERIAL PRIMARY KEY,
    context_keyword VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    success_rate FLOAT DEFAULT 1.0,
    avg_duration_ms FLOAT,
    last_seen_at TIMESTAMP DEFAULT NOW(),
    first_seen_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(context_keyword, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_context_tool_keyword ON context_tool_mapping(context_keyword);
CREATE INDEX IF NOT EXISTS idx_context_tool_name ON context_tool_mapping(tool_name);
CREATE INDEX IF NOT EXISTS idx_context_tool_count ON context_tool_mapping(occurrence_count DESC);

-- Session type patterns (coding, planning, research, etc.)
CREATE TABLE IF NOT EXISTS session_type_patterns (
    id SERIAL PRIMARY KEY,
    session_type VARCHAR(50) NOT NULL,  -- coding, planning, research, communication, etc.
    indicators JSONB NOT NULL,  -- {"tools": ["read_project_file"], "keywords": ["code", "function"]}
    tool_preferences JSONB,  -- {"preferred": ["search_knowledge"], "avoid": []}
    occurrence_count INTEGER DEFAULT 1,
    confidence FLOAT DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_type ON session_type_patterns(session_type);

-- Insert default session types
INSERT INTO session_type_patterns (session_type, indicators, tool_preferences, confidence) VALUES
    ('coding',
     '{"tools": ["read_project_file", "write_project_file", "read_my_source_files"], "keywords": ["code", "function", "error", "bug", "implement"]}',
     '{"preferred": ["read_project_file", "search_knowledge"], "context_load": ["recent_errors", "project_structure"]}',
     0.8),
    ('planning',
     '{"tools": ["list_projects", "get_calendar_events", "create_calendar_event"], "keywords": ["plan", "schedule", "meeting", "deadline"]}',
     '{"preferred": ["get_calendar_events", "list_projects"], "context_load": ["upcoming_events", "project_status"]}',
     0.8),
    ('research',
     '{"tools": ["search_knowledge", "web_search", "run_research"], "keywords": ["search", "find", "research", "info", "learn"]}',
     '{"preferred": ["search_knowledge", "web_search"], "context_load": ["recent_searches", "interests"]}',
     0.8),
    ('communication',
     '{"tools": ["send_email", "get_gmail_messages"], "keywords": ["email", "message", "reply", "send"]}',
     '{"preferred": ["get_gmail_messages", "send_email"], "context_load": ["recent_emails", "contacts"]}',
     0.8),
    ('introspection',
     '{"tools": ["system_health_check", "self_validation_pulse", "get_my_tool_usage"], "keywords": ["status", "health", "check", "how are you"]}',
     '{"preferred": ["system_health_check", "get_my_tool_usage"], "context_load": ["system_status"]}',
     0.8)
ON CONFLICT DO NOTHING;

-- Tool usage trends (daily aggregates for trend analysis)
CREATE TABLE IF NOT EXISTS tool_usage_trends (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    call_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    avg_duration_ms FLOAT,
    unique_contexts INTEGER DEFAULT 0,
    UNIQUE(date, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_tool_trends_date ON tool_usage_trends(date DESC);
CREATE INDEX IF NOT EXISTS idx_tool_trends_tool ON tool_usage_trends(tool_name);

-- View for quick analytics access
CREATE OR REPLACE VIEW v_tool_analytics AS
SELECT
    ta.tool_name,
    COUNT(*) as total_calls,
    SUM(CASE WHEN ta.success THEN 1 ELSE 0 END) as success_count,
    ROUND(AVG(ta.duration_ms)::numeric, 2) as avg_duration_ms,
    ROUND(100.0 * SUM(CASE WHEN ta.success THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as success_rate,
    MIN(ta.created_at) as first_used,
    MAX(ta.created_at) as last_used,
    COUNT(DISTINCT DATE(ta.created_at)) as active_days
FROM tool_audit ta
WHERE ta.created_at > NOW() - INTERVAL '30 days'
GROUP BY ta.tool_name
ORDER BY COUNT(*) DESC;
