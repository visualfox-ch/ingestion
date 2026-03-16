-- Migration: 092_playbook_learning_confidence
-- Tracks Jarvis's confidence about when to save learnings automatically vs. ask
-- Created: 2026-03-14

-- Track user responses to "soll ich speichern?" questions
CREATE TABLE IF NOT EXISTS playbook_learning_feedback (
    id SERIAL PRIMARY KEY,
    playbook_domain VARCHAR(100) NOT NULL,
    learning_type VARCHAR(100) NOT NULL,  -- style_element, example, signature_phrase, etc.
    context_pattern TEXT,                  -- What triggered the question (e.g., "user shared own post")
    user_response VARCHAR(20) NOT NULL,    -- 'yes', 'no', 'later', 'always', 'never'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learning_feedback_domain ON playbook_learning_feedback(playbook_domain);
CREATE INDEX IF NOT EXISTS idx_learning_feedback_type ON playbook_learning_feedback(learning_type);

-- Aggregated confidence scores per learning type
CREATE TABLE IF NOT EXISTS playbook_learning_confidence (
    id SERIAL PRIMARY KEY,
    playbook_domain VARCHAR(100) NOT NULL,
    learning_type VARCHAR(100) NOT NULL,
    context_pattern VARCHAR(255),          -- e.g., "user_shared_post", "user_corrected", "user_mentioned_contact"
    auto_save_confidence FLOAT DEFAULT 0.5, -- 0.0 = always ask, 1.0 = always auto-save
    total_asks INTEGER DEFAULT 0,
    total_yes INTEGER DEFAULT 0,
    total_no INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(playbook_domain, learning_type, context_pattern)
);

CREATE INDEX IF NOT EXISTS idx_learning_confidence_domain ON playbook_learning_confidence(playbook_domain);

-- Insert initial confidence levels based on common patterns
INSERT INTO playbook_learning_confidence (playbook_domain, learning_type, context_pattern, auto_save_confidence, total_asks, total_yes)
VALUES
    -- LinkedIn: High confidence auto-save patterns
    ('linkedin_comment', 'example', 'user_shared_own_post', 0.8, 5, 4),
    ('linkedin_comment', 'signature_phrase', 'user_uses_repeatedly', 0.7, 3, 2),
    ('linkedin_comment', 'network_contact', 'user_mentions_with_context', 0.6, 2, 1),

    -- LinkedIn: Medium confidence - ask first
    ('linkedin_comment', 'style_element', 'user_feedback', 0.5, 0, 0),
    ('linkedin_comment', 'style_element', 'pattern_detected', 0.4, 0, 0),

    -- LinkedIn: Low confidence - always ask
    ('linkedin_comment', 'forbidden', 'user_dislikes_phrase', 0.3, 0, 0),
    ('linkedin_comment', 'avoid', 'inferred_preference', 0.2, 0, 0)
ON CONFLICT (playbook_domain, learning_type, context_pattern) DO NOTHING;

-- Function to update confidence based on user response
-- Called after user responds to "soll ich speichern?"
CREATE OR REPLACE FUNCTION update_learning_confidence(
    p_domain VARCHAR,
    p_type VARCHAR,
    p_pattern VARCHAR,
    p_response VARCHAR
) RETURNS VOID AS $$
DECLARE
    v_delta FLOAT;
BEGIN
    -- Determine confidence delta based on response
    v_delta := CASE p_response
        WHEN 'yes' THEN 0.1
        WHEN 'always' THEN 0.3
        WHEN 'no' THEN -0.1
        WHEN 'never' THEN -0.3
        ELSE 0.0
    END;

    -- Upsert confidence record
    INSERT INTO playbook_learning_confidence
        (playbook_domain, learning_type, context_pattern, auto_save_confidence, total_asks, total_yes, total_no)
    VALUES
        (p_domain, p_type, p_pattern, 0.5 + v_delta, 1,
         CASE WHEN p_response IN ('yes', 'always') THEN 1 ELSE 0 END,
         CASE WHEN p_response IN ('no', 'never') THEN 1 ELSE 0 END)
    ON CONFLICT (playbook_domain, learning_type, context_pattern) DO UPDATE SET
        auto_save_confidence = LEAST(1.0, GREATEST(0.0,
            playbook_learning_confidence.auto_save_confidence + v_delta)),
        total_asks = playbook_learning_confidence.total_asks + 1,
        total_yes = playbook_learning_confidence.total_yes +
            CASE WHEN p_response IN ('yes', 'always') THEN 1 ELSE 0 END,
        total_no = playbook_learning_confidence.total_no +
            CASE WHEN p_response IN ('no', 'never') THEN 1 ELSE 0 END,
        last_updated = NOW();

    -- Also record the individual feedback
    INSERT INTO playbook_learning_feedback (playbook_domain, learning_type, context_pattern, user_response)
    VALUES (p_domain, p_type, p_pattern, p_response);
END;
$$ LANGUAGE plpgsql;
