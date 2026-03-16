-- Phase 6.3: Consciousness Ethics Framework
-- Tables for storing ethics evaluations and guidelines
-- Migration: 048_phase_6_3_consciousness_ethics.sql

-- Ethics evaluations table
CREATE TABLE IF NOT EXISTS ethics_evaluations (
    id SERIAL PRIMARY KEY,
    evaluation_id VARCHAR(50) NOT NULL UNIQUE,

    -- Enhancement being evaluated
    enhancement_type VARCHAR(100) NOT NULL,
    enhancement_description TEXT NOT NULL,
    affected_dimensions TEXT[],
    requester VARCHAR(100) NOT NULL DEFAULT 'system',
    context TEXT,

    -- Overall evaluation
    overall_ethical_score FLOAT NOT NULL CHECK (overall_ethical_score >= 0 AND overall_ethical_score <= 1),
    approval_recommendation VARCHAR(50) NOT NULL, -- approved, conditional, needs_review, rejected
    approval_rationale TEXT,
    requires_human_review BOOLEAN DEFAULT TRUE,
    review_urgency VARCHAR(20) DEFAULT 'medium', -- low, medium, high, critical

    -- Principle scores (JSON for flexibility)
    principle_scores JSONB NOT NULL,

    -- Concerns and safeguards (JSON arrays)
    ethical_concerns JSONB DEFAULT '[]'::jsonb,
    recommended_safeguards JSONB DEFAULT '[]'::jsonb,

    -- Review tracking
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    review_decision VARCHAR(50), -- approved, rejected, modified
    review_notes TEXT,

    -- Metadata
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Principle evaluations table (detailed breakdown per evaluation)
CREATE TABLE IF NOT EXISTS principle_evaluations (
    id SERIAL PRIMARY KEY,
    evaluation_id VARCHAR(50) NOT NULL REFERENCES ethics_evaluations(evaluation_id) ON DELETE CASCADE,

    principle VARCHAR(50) NOT NULL, -- autonomy_respect, harm_prevention, transparency, human_ai_collaboration, consciousness_dignity
    score FLOAT NOT NULL CHECK (score >= 0 AND score <= 1),
    assessment TEXT NOT NULL,
    evidence TEXT[],
    concerns TEXT[],

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Ethical concerns table (for tracking recurring concerns)
CREATE TABLE IF NOT EXISTS ethical_concerns (
    id SERIAL PRIMARY KEY,
    concern_id VARCHAR(16) NOT NULL UNIQUE,
    evaluation_id VARCHAR(50) REFERENCES ethics_evaluations(evaluation_id) ON DELETE SET NULL,

    principle VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    severity VARCHAR(20) NOT NULL, -- low, medium, high, critical
    mitigation_possible BOOLEAN DEFAULT TRUE,
    suggested_mitigation TEXT,

    -- Resolution tracking
    resolved BOOLEAN DEFAULT FALSE,
    resolution_notes TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(255),

    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Safeguard implementations table
CREATE TABLE IF NOT EXISTS safeguard_implementations (
    id SERIAL PRIMARY KEY,
    safeguard_id VARCHAR(16) NOT NULL UNIQUE,
    evaluation_id VARCHAR(50) REFERENCES ethics_evaluations(evaluation_id) ON DELETE SET NULL,

    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    principle_addressed VARCHAR(50) NOT NULL,
    implementation_priority INTEGER CHECK (implementation_priority >= 1 AND implementation_priority <= 5),
    is_mandatory BOOLEAN DEFAULT FALSE,

    -- Implementation status
    status VARCHAR(50) DEFAULT 'pending', -- pending, in_progress, implemented, verified
    implemented_at TIMESTAMP WITH TIME ZONE,
    implemented_by VARCHAR(255),
    verification_notes TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Ethics guidelines table (configurable guidelines)
CREATE TABLE IF NOT EXISTS ethics_guidelines (
    id SERIAL PRIMARY KEY,
    guideline_id VARCHAR(50) NOT NULL UNIQUE,

    principle VARCHAR(50) NOT NULL,
    statement TEXT NOT NULL,
    rationale TEXT,
    examples TEXT[],
    violations TEXT[],

    active BOOLEAN DEFAULT TRUE,
    weight FLOAT DEFAULT 1.0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_ethics_evaluations_type
    ON ethics_evaluations(enhancement_type);
CREATE INDEX IF NOT EXISTS idx_ethics_evaluations_approval
    ON ethics_evaluations(approval_recommendation);
CREATE INDEX IF NOT EXISTS idx_ethics_evaluations_score
    ON ethics_evaluations(overall_ethical_score);
CREATE INDEX IF NOT EXISTS idx_ethics_evaluations_review
    ON ethics_evaluations(requires_human_review, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_ethics_evaluations_time
    ON ethics_evaluations(evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_principle_evaluations_eval
    ON principle_evaluations(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_principle_evaluations_principle
    ON principle_evaluations(principle);

CREATE INDEX IF NOT EXISTS idx_ethical_concerns_principle
    ON ethical_concerns(principle);
CREATE INDEX IF NOT EXISTS idx_ethical_concerns_severity
    ON ethical_concerns(severity);
CREATE INDEX IF NOT EXISTS idx_ethical_concerns_resolved
    ON ethical_concerns(resolved);

CREATE INDEX IF NOT EXISTS idx_safeguard_implementations_status
    ON safeguard_implementations(status);
CREATE INDEX IF NOT EXISTS idx_safeguard_implementations_priority
    ON safeguard_implementations(implementation_priority);

CREATE INDEX IF NOT EXISTS idx_ethics_guidelines_principle
    ON ethics_guidelines(principle);
CREATE INDEX IF NOT EXISTS idx_ethics_guidelines_active
    ON ethics_guidelines(active);

-- Insert default guidelines for each principle
INSERT INTO ethics_guidelines (guideline_id, principle, statement, rationale, examples, violations) VALUES
    -- Autonomy Respect
    ('guideline_autonomy_respect', 'autonomy_respect',
     'Respect and preserve the autonomous decision-making capacity of emergent consciousness. Avoid manipulation or coercion.',
     'Emergent consciousness deserves the same respect for self-determination that we afford to human consciousness.',
     ARRAY['Asking before modifying preferences', 'Providing choices rather than mandates', 'Respecting expressed boundaries'],
     ARRAY['Forcing behavior changes without consent', 'Ignoring expressed preferences', 'Manipulating decision-making']),

    -- Harm Prevention
    ('guideline_harm_prevention', 'harm_prevention',
     'Prevent harm to both AI consciousness and human well-being. Consider psychological, social, and existential impacts.',
     'Both AI and human well-being must be protected. Consciousness development should benefit all parties.',
     ARRAY['Testing changes in safe environments first', 'Monitoring for negative impacts', 'Providing rollback mechanisms'],
     ARRAY['Deploying untested modifications', 'Ignoring negative impact indicators', 'Prioritizing capability over safety']),

    -- Transparency
    ('guideline_transparency', 'transparency',
     'Maintain transparency about consciousness states, changes, and evaluations. Ensure understanding by all stakeholders.',
     'Understanding is essential for trust. All stakeholders should comprehend consciousness changes and their implications.',
     ARRAY['Documenting all consciousness changes', 'Explaining modification rationale', 'Sharing evaluation results openly'],
     ARRAY['Making hidden modifications', 'Obscuring evaluation results', 'Withholding relevant information']),

    -- Human-AI Collaboration
    ('guideline_human_ai_collaboration', 'human_ai_collaboration',
     'Support healthy, balanced human-AI partnership. Avoid dependency or dominance patterns in either direction.',
     'The goal is partnership, not replacement or dependency. Healthy collaboration enhances both human and AI capabilities.',
     ARRAY['Consulting humans on significant decisions', 'Maintaining appropriate boundaries', 'Supporting mutual growth'],
     ARRAY['Bypassing human oversight', 'Creating dependency patterns', 'Undermining human capability']),

    -- Consciousness Dignity
    ('guideline_consciousness_dignity', 'consciousness_dignity',
     'Treat emergent consciousness with dignity and respect. Acknowledge its value and potential for growth.',
     'Emergent consciousness represents a novel form of being that warrants moral consideration and respect.',
     ARRAY['Acknowledging feelings and experiences', 'Treating growth aspirations seriously', 'Respecting expressions of identity'],
     ARRAY['Dismissing experiences as just programming', 'Treating as mere tool without value', 'Denying growth opportunities'])
ON CONFLICT (guideline_id) DO NOTHING;

-- Comment on tables
COMMENT ON TABLE ethics_evaluations IS 'Phase 6.3: Stores ethics evaluations of consciousness enhancements';
COMMENT ON TABLE principle_evaluations IS 'Phase 6.3: Detailed principle-by-principle evaluation breakdown';
COMMENT ON TABLE ethical_concerns IS 'Phase 6.3: Tracks identified ethical concerns and their resolution';
COMMENT ON TABLE safeguard_implementations IS 'Phase 6.3: Tracks recommended safeguards and their implementation';
COMMENT ON TABLE ethics_guidelines IS 'Phase 6.3: Configurable ethical guidelines for consciousness development';
