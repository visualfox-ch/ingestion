-- Migration 072: Research Pipeline Schema
-- Generic, database-driven research infrastructure for Perplexity/Sonar Pro integration
-- Created: 2026-03-13

-- ============================================================================
-- RESEARCH DOMAINS
-- Domain configurations with prompts and output schemas
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_domains (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Research configuration
    default_model VARCHAR(100) DEFAULT 'sonar-pro',
    search_recency_filter VARCHAR(50) DEFAULT 'week',  -- day, week, month, year
    max_tokens INTEGER DEFAULT 4096,
    temperature NUMERIC(3,2) DEFAULT 0.2,

    -- Prompt template with placeholders: {topic}, {context}, {date}
    prompt_template TEXT NOT NULL,

    -- JSON schema for structured output parsing
    output_schema JSONB,

    -- Scheduling
    default_schedule VARCHAR(100),  -- cron expression or null for manual
    priority INTEGER DEFAULT 5,  -- 1-10, higher = more important

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_research_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_research_domains_active ON research_domains(is_active) WHERE is_active = TRUE;


-- ============================================================================
-- RESEARCH TOPICS
-- Specific topics within each domain
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_topics (
    id SERIAL PRIMARY KEY,
    domain_id INTEGER REFERENCES research_domains(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    query_template TEXT,  -- Optional override of domain prompt
    context TEXT,  -- Additional context for this topic

    -- Topic-specific settings
    priority INTEGER DEFAULT 5,
    search_recency_filter VARCHAR(50),  -- Override domain default

    -- Tracking
    is_active BOOLEAN DEFAULT TRUE,
    last_researched_at TIMESTAMPTZ,
    research_count INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(domain_id, name)
);

CREATE INDEX idx_research_topics_domain ON research_topics(domain_id);
CREATE INDEX idx_research_topics_active ON research_topics(is_active) WHERE is_active = TRUE;


-- ============================================================================
-- TAGS
-- Flexible tagging system for categorization
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    category VARCHAR(100),  -- Optional grouping (e.g., 'provider', 'capability', 'status')
    color VARCHAR(7),  -- Hex color for UI
    description TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_research_tags_category ON research_tags(category);


-- ============================================================================
-- RESEARCH ITEMS
-- Individual research findings/entries
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_items (
    id SERIAL PRIMARY KEY,
    domain_id INTEGER REFERENCES research_domains(id) ON DELETE CASCADE,
    topic_id INTEGER REFERENCES research_topics(id) ON DELETE SET NULL,

    -- Core content
    title VARCHAR(500) NOT NULL,
    summary TEXT,
    content TEXT,  -- Full content/details

    -- Structured data from output_schema parsing
    structured_data JSONB,

    -- Source tracking
    sources JSONB,  -- Array of {url, title, domain, snippet}
    source_count INTEGER DEFAULT 0,

    -- Research metadata
    query_used TEXT,
    model_used VARCHAR(100),
    research_session_id UUID,  -- Groups items from same research run

    -- Quality indicators
    confidence_score NUMERIC(3,2),  -- 0-1 from Perplexity
    relevance_score NUMERIC(3,2),  -- 0-1 calculated

    -- Embedding for semantic search
    embedding_id VARCHAR(100),  -- Reference to Qdrant

    -- Status
    status VARCHAR(50) DEFAULT 'new',  -- new, reviewed, archived, flagged
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(100),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_research_items_domain ON research_items(domain_id);
CREATE INDEX idx_research_items_topic ON research_items(topic_id);
CREATE INDEX idx_research_items_session ON research_items(research_session_id);
CREATE INDEX idx_research_items_status ON research_items(status);
CREATE INDEX idx_research_items_created ON research_items(created_at DESC);
CREATE INDEX idx_research_items_structured ON research_items USING GIN (structured_data);


-- ============================================================================
-- RESEARCH ITEM TAGS (Join Table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_item_tags (
    item_id INTEGER REFERENCES research_items(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES research_tags(id) ON DELETE CASCADE,

    added_at TIMESTAMPTZ DEFAULT NOW(),
    added_by VARCHAR(100) DEFAULT 'system',

    PRIMARY KEY (item_id, tag_id)
);

CREATE INDEX idx_research_item_tags_tag ON research_item_tags(tag_id);


-- ============================================================================
-- RESEARCH REPORTS
-- Aggregated reports/summaries
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_reports (
    id SERIAL PRIMARY KEY,
    domain_id INTEGER REFERENCES research_domains(id) ON DELETE CASCADE,

    -- Report metadata
    title VARCHAR(500) NOT NULL,
    report_type VARCHAR(100) DEFAULT 'periodic',  -- periodic, comparative, deep_dive, summary
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,

    -- Content
    executive_summary TEXT,
    full_report TEXT,
    key_findings JSONB,  -- Array of key points
    recommendations JSONB,

    -- Statistics
    items_analyzed INTEGER DEFAULT 0,
    topics_covered INTEGER DEFAULT 0,

    -- Generation metadata
    generated_by VARCHAR(100),  -- model or service
    generation_prompt TEXT,

    -- Status
    status VARCHAR(50) DEFAULT 'draft',  -- draft, published, archived
    published_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_research_reports_domain ON research_reports(domain_id);
CREATE INDEX idx_research_reports_type ON research_reports(report_type);
CREATE INDEX idx_research_reports_status ON research_reports(status);


-- ============================================================================
-- RESEARCH SESSIONS
-- Track individual research runs
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id INTEGER REFERENCES research_domains(id) ON DELETE CASCADE,

    -- Trigger info
    triggered_by VARCHAR(100) DEFAULT 'manual',  -- manual, scheduled, tool_call
    trigger_context JSONB,

    -- Execution
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'running',  -- running, completed, failed, cancelled

    -- Results
    topics_processed INTEGER DEFAULT 0,
    items_created INTEGER DEFAULT 0,
    errors JSONB,

    -- API usage
    api_calls INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    estimated_cost NUMERIC(10,4)
);

CREATE INDEX idx_research_sessions_domain ON research_sessions(domain_id);
CREATE INDEX idx_research_sessions_status ON research_sessions(status);


-- ============================================================================
-- PERPLEXITY API CONFIG
-- API configuration and rate limiting
-- ============================================================================

CREATE TABLE IF NOT EXISTS perplexity_config (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT,
    description TEXT,

    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default config
INSERT INTO perplexity_config (key, value, description) VALUES
    ('api_endpoint', 'https://api.perplexity.ai/chat/completions', 'Perplexity API endpoint'),
    ('default_model', 'sonar-pro', 'Default model for research'),
    ('rate_limit_rpm', '60', 'Requests per minute limit'),
    ('rate_limit_daily', '1000', 'Daily request limit'),
    ('max_concurrent', '3', 'Max concurrent requests'),
    ('retry_attempts', '3', 'Number of retry attempts'),
    ('retry_delay_ms', '1000', 'Delay between retries in ms')
ON CONFLICT (key) DO NOTHING;


-- ============================================================================
-- SEED DATA: AI Tools Domain
-- ============================================================================

INSERT INTO research_domains (
    name,
    display_name,
    description,
    default_model,
    search_recency_filter,
    prompt_template,
    output_schema,
    default_schedule,
    priority
) VALUES (
    'ai_tools',
    'AI Tools & Platforms',
    'Research on AI tools, platforms, APIs, and services. Tracks new releases, updates, pricing changes, and capabilities.',
    'sonar-pro',
    'week',
    E'Research the latest developments for: {topic}

Focus on:
1. New features and capabilities announced in the last {recency}
2. Pricing changes or new tiers
3. API updates and breaking changes
4. Performance benchmarks if available
5. Integration possibilities with other tools
6. User feedback and adoption trends

Context: {context}

Provide structured information with sources. Be specific about dates and version numbers.',
    '{
        "type": "object",
        "properties": {
            "tool_name": {"type": "string"},
            "provider": {"type": "string"},
            "latest_version": {"type": "string"},
            "release_date": {"type": "string"},
            "key_features": {"type": "array", "items": {"type": "string"}},
            "pricing": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "tiers": {"type": "array", "items": {"type": "object"}}
                }
            },
            "api_changes": {"type": "array", "items": {"type": "string"}},
            "integrations": {"type": "array", "items": {"type": "string"}},
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]}
        }
    }'::jsonb,
    '0 9 * * 1',  -- Every Monday at 9:00
    8
) ON CONFLICT (name) DO UPDATE SET
    prompt_template = EXCLUDED.prompt_template,
    output_schema = EXCLUDED.output_schema,
    updated_at = NOW();


-- ============================================================================
-- SEED DATA: Initial Topics for AI Tools
-- ============================================================================

INSERT INTO research_topics (domain_id, name, context, priority) VALUES
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'Claude API', 'Anthropic''s Claude models and API', 9),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'OpenAI GPT', 'OpenAI GPT models, ChatGPT, API', 9),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'Perplexity AI', 'Perplexity search and Sonar models', 8),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'Cursor IDE', 'AI-powered code editor', 7),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'GitHub Copilot', 'AI pair programming', 7),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'Ollama', 'Local LLM running', 6),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'LangChain', 'LLM application framework', 6),
    ((SELECT id FROM research_domains WHERE name = 'ai_tools'), 'Vector Databases', 'Qdrant, Pinecone, Weaviate, ChromaDB', 6)
ON CONFLICT (domain_id, name) DO NOTHING;


-- ============================================================================
-- SEED DATA: Common Tags
-- ============================================================================

INSERT INTO research_tags (name, category, color, description) VALUES
    -- Provider tags
    ('anthropic', 'provider', '#D97706', 'Anthropic/Claude related'),
    ('openai', 'provider', '#10B981', 'OpenAI/GPT related'),
    ('google', 'provider', '#3B82F6', 'Google AI related'),
    ('meta', 'provider', '#8B5CF6', 'Meta/Llama related'),
    ('mistral', 'provider', '#EC4899', 'Mistral AI related'),

    -- Capability tags
    ('coding', 'capability', '#6366F1', 'Code generation/analysis'),
    ('reasoning', 'capability', '#F59E0B', 'Reasoning and logic'),
    ('vision', 'capability', '#10B981', 'Image understanding'),
    ('voice', 'capability', '#EF4444', 'Voice/audio processing'),
    ('agents', 'capability', '#8B5CF6', 'Autonomous agents'),

    -- Status tags
    ('breaking_change', 'status', '#EF4444', 'Breaking API change'),
    ('new_release', 'status', '#10B981', 'New version released'),
    ('price_change', 'status', '#F59E0B', 'Pricing update'),
    ('beta', 'status', '#6366F1', 'Beta/preview feature'),
    ('deprecated', 'status', '#6B7280', 'Deprecated feature'),

    -- Priority tags
    ('urgent', 'priority', '#EF4444', 'Requires immediate attention'),
    ('important', 'priority', '#F59E0B', 'High priority'),
    ('review_needed', 'priority', '#3B82F6', 'Needs human review')
ON CONFLICT (name) DO NOTHING;


-- ============================================================================
-- UPDATE TRIGGERS
-- ============================================================================

CREATE OR REPLACE FUNCTION update_research_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_research_domains_updated ON research_domains;
CREATE TRIGGER trg_research_domains_updated
    BEFORE UPDATE ON research_domains
    FOR EACH ROW EXECUTE FUNCTION update_research_timestamp();

DROP TRIGGER IF EXISTS trg_research_topics_updated ON research_topics;
CREATE TRIGGER trg_research_topics_updated
    BEFORE UPDATE ON research_topics
    FOR EACH ROW EXECUTE FUNCTION update_research_timestamp();

DROP TRIGGER IF EXISTS trg_research_items_updated ON research_items;
CREATE TRIGGER trg_research_items_updated
    BEFORE UPDATE ON research_items
    FOR EACH ROW EXECUTE FUNCTION update_research_timestamp();

DROP TRIGGER IF EXISTS trg_research_reports_updated ON research_reports;
CREATE TRIGGER trg_research_reports_updated
    BEFORE UPDATE ON research_reports
    FOR EACH ROW EXECUTE FUNCTION update_research_timestamp();


-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_research_domain_stats AS
SELECT
    d.id,
    d.name,
    d.display_name,
    d.is_active,
    d.last_research_at,
    COUNT(DISTINCT t.id) as topic_count,
    COUNT(DISTINCT i.id) as item_count,
    COUNT(DISTINCT r.id) as report_count,
    MAX(i.created_at) as latest_item_at
FROM research_domains d
LEFT JOIN research_topics t ON t.domain_id = d.id AND t.is_active = TRUE
LEFT JOIN research_items i ON i.domain_id = d.id
LEFT JOIN research_reports r ON r.domain_id = d.id
GROUP BY d.id;


CREATE OR REPLACE VIEW v_recent_research_items AS
SELECT
    i.id,
    i.title,
    i.summary,
    i.created_at,
    i.status,
    i.confidence_score,
    d.name as domain_name,
    t.name as topic_name,
    array_agg(DISTINCT rt.name) FILTER (WHERE rt.name IS NOT NULL) as tags
FROM research_items i
JOIN research_domains d ON d.id = i.domain_id
LEFT JOIN research_topics t ON t.id = i.topic_id
LEFT JOIN research_item_tags it ON it.item_id = i.id
LEFT JOIN research_tags rt ON rt.id = it.tag_id
WHERE i.created_at > NOW() - INTERVAL '7 days'
GROUP BY i.id, d.name, t.name
ORDER BY i.created_at DESC;


-- ============================================================================
-- DONE
-- ============================================================================

COMMENT ON TABLE research_domains IS 'Domain configurations for research pipeline (e.g., ai_tools, market_trends)';
COMMENT ON TABLE research_topics IS 'Specific topics within each research domain';
COMMENT ON TABLE research_items IS 'Individual research findings with structured data';
COMMENT ON TABLE research_reports IS 'Aggregated reports and summaries';
COMMENT ON TABLE research_sessions IS 'Tracks individual research runs for monitoring';
