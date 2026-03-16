-- Phase S1: Citation-Grounding System
-- Anti-Halluzination Layer: Link facts to verifiable sources
-- Date: 2026-03-15

-- ============================================
-- Add verification status to learned_facts
-- ============================================

ALTER TABLE learned_facts
ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'unverified'
CHECK (verification_status IN ('unverified', 'partially_verified', 'verified', 'contradicted'));

ALTER TABLE learned_facts
ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;

ALTER TABLE learned_facts
ADD COLUMN IF NOT EXISTS verification_count INTEGER DEFAULT 0;

COMMENT ON COLUMN learned_facts.verification_status IS 'S1: unverified=no sources, partially_verified=some sources, verified=multiple trusted sources, contradicted=conflicting sources';

-- ============================================
-- Citation Sources Registry
-- ============================================

CREATE TABLE IF NOT EXISTS citation_sources (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    display_name TEXT,
    trust_score FLOAT DEFAULT 0.5 CHECK (trust_score >= 0 AND trust_score <= 1.0),
    source_type TEXT DEFAULT 'web' CHECK (source_type IN ('web', 'academic', 'official', 'news', 'social', 'internal')),
    is_trusted BOOLEAN DEFAULT FALSE,
    citation_count INTEGER DEFAULT 0,
    last_cited_at TIMESTAMPTZ,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert known trusted sources
INSERT INTO citation_sources (domain, display_name, trust_score, source_type, is_trusted) VALUES
    ('wikipedia.org', 'Wikipedia', 0.7, 'web', TRUE),
    ('arxiv.org', 'arXiv', 0.9, 'academic', TRUE),
    ('github.com', 'GitHub', 0.8, 'web', TRUE),
    ('docs.python.org', 'Python Docs', 0.95, 'official', TRUE),
    ('anthropic.com', 'Anthropic', 0.95, 'official', TRUE),
    ('openai.com', 'OpenAI', 0.9, 'official', TRUE),
    ('admin.ch', 'Swiss Government', 0.95, 'official', TRUE),
    ('nzz.ch', 'NZZ', 0.75, 'news', TRUE),
    ('reuters.com', 'Reuters', 0.85, 'news', TRUE)
ON CONFLICT (domain) DO NOTHING;

-- ============================================
-- Fact Citations Table (Many-to-Many)
-- ============================================

CREATE TABLE IF NOT EXISTS fact_citations (
    id SERIAL PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES learned_facts(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES citation_sources(id) ON DELETE SET NULL,

    -- Citation details
    url TEXT NOT NULL,
    title TEXT,
    excerpt TEXT,
    access_date TIMESTAMPTZ DEFAULT NOW(),

    -- Quality metrics
    relevance_score FLOAT DEFAULT 0.5 CHECK (relevance_score >= 0 AND relevance_score <= 1.0),
    supports_fact BOOLEAN DEFAULT TRUE,  -- FALSE = contradicts

    -- Context
    context JSONB,  -- query used, research session, etc.
    created_by TEXT DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(fact_id, url)
);

CREATE INDEX IF NOT EXISTS idx_fact_citations_fact ON fact_citations(fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_citations_source ON fact_citations(source_id);
CREATE INDEX IF NOT EXISTS idx_fact_citations_supports ON fact_citations(supports_fact);

-- ============================================
-- Research Result Citations
-- ============================================

-- Link research results to their sources
ALTER TABLE research_items
ADD COLUMN IF NOT EXISTS citation_data JSONB;

COMMENT ON COLUMN research_items.citation_data IS 'S1: Structured citation info extracted from research';

-- ============================================
-- Verification Requests (Manual Review Queue)
-- ============================================

CREATE TABLE IF NOT EXISTS verification_requests (
    id SERIAL PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES learned_facts(id) ON DELETE CASCADE,
    request_reason TEXT,
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'rejected')),
    assigned_to TEXT,
    resolution TEXT,
    verified_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_verification_requests_status ON verification_requests(status);
CREATE INDEX IF NOT EXISTS idx_verification_requests_priority ON verification_requests(priority DESC);

-- ============================================
-- Useful Views
-- ============================================

-- Facts needing verification
CREATE OR REPLACE VIEW v_unverified_facts AS
SELECT
    f.id,
    f.key,
    f.value_text,
    f.confidence,
    f.source as original_source,
    f.created_at,
    COUNT(fc.id) as citation_count,
    ARRAY_AGG(DISTINCT cs.domain) FILTER (WHERE cs.domain IS NOT NULL) as cited_domains
FROM learned_facts f
LEFT JOIN fact_citations fc ON f.id = fc.fact_id
LEFT JOIN citation_sources cs ON fc.source_id = cs.id
WHERE f.verification_status = 'unverified'
  AND f.status = 'active'
GROUP BY f.id
ORDER BY f.created_at DESC;

-- Facts with conflicting citations
CREATE OR REPLACE VIEW v_conflicting_facts AS
SELECT
    f.id,
    f.key,
    f.value_text,
    SUM(CASE WHEN fc.supports_fact THEN 1 ELSE 0 END) as supporting_citations,
    SUM(CASE WHEN NOT fc.supports_fact THEN 1 ELSE 0 END) as contradicting_citations
FROM learned_facts f
JOIN fact_citations fc ON f.id = fc.fact_id
GROUP BY f.id
HAVING SUM(CASE WHEN NOT fc.supports_fact THEN 1 ELSE 0 END) > 0;

-- Citation source statistics
CREATE OR REPLACE VIEW v_citation_source_stats AS
SELECT
    cs.domain,
    cs.display_name,
    cs.trust_score,
    cs.source_type,
    cs.is_trusted,
    cs.citation_count,
    COUNT(fc.id) as actual_citations,
    AVG(fc.relevance_score) as avg_relevance
FROM citation_sources cs
LEFT JOIN fact_citations fc ON cs.id = fc.source_id
GROUP BY cs.id
ORDER BY cs.citation_count DESC;

-- ============================================
-- Helper Functions
-- ============================================

-- Update fact verification status based on citations
CREATE OR REPLACE FUNCTION update_fact_verification_status(p_fact_id TEXT)
RETURNS TEXT AS $$
DECLARE
    v_citation_count INTEGER;
    v_trusted_count INTEGER;
    v_contradicting_count INTEGER;
    v_new_status TEXT;
BEGIN
    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE cs.is_trusted AND fc.supports_fact),
        COUNT(*) FILTER (WHERE NOT fc.supports_fact)
    INTO v_citation_count, v_trusted_count, v_contradicting_count
    FROM fact_citations fc
    LEFT JOIN citation_sources cs ON fc.source_id = cs.id
    WHERE fc.fact_id = p_fact_id;

    -- Determine status
    IF v_contradicting_count > 0 THEN
        v_new_status := 'contradicted';
    ELSIF v_trusted_count >= 2 THEN
        v_new_status := 'verified';
    ELSIF v_citation_count > 0 THEN
        v_new_status := 'partially_verified';
    ELSE
        v_new_status := 'unverified';
    END IF;

    -- Update fact
    UPDATE learned_facts
    SET verification_status = v_new_status,
        verification_count = v_citation_count,
        last_verified_at = NOW()
    WHERE id = p_fact_id;

    RETURN v_new_status;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Comments
-- ============================================

COMMENT ON TABLE fact_citations IS 'S1: Links facts to verifiable sources for anti-hallucination';
COMMENT ON TABLE citation_sources IS 'S1: Registry of citation sources with trust scores';
COMMENT ON TABLE verification_requests IS 'S1: Queue for manual fact verification';
COMMENT ON VIEW v_unverified_facts IS 'S1: Facts that need source verification';
COMMENT ON VIEW v_conflicting_facts IS 'S1: Facts with contradicting citations';
COMMENT ON FUNCTION update_fact_verification_status IS 'S1: Recalculates verification status based on citations';

-- ============================================
-- Set Risk Tiers for Citation Tools
-- ============================================

-- Tier 0 (safe, read-only): Query/stats tools
UPDATE jarvis_tools SET risk_tier = 0 WHERE name IN (
    'get_fact_citations',
    'get_verification_status',
    'get_unverified_facts',
    'get_conflicting_facts',
    'get_citation_stats',
    'search_citations'
);

-- Tier 1 (standard): Citation additions (confidence >= 80%)
UPDATE jarvis_tools SET risk_tier = 1 WHERE name IN (
    'cite_fact',
    'request_fact_verification'
);

-- Tier 2 (sensitive): Modify trust/verification status
UPDATE jarvis_tools SET risk_tier = 2 WHERE name IN (
    'verify_fact',
    'register_citation_source'
);
