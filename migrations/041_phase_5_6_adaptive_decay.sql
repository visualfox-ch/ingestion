-- Migration 041: Phase 5.6 Adaptive Decay Modeling
-- Adds adaptive decay learning tables and optimization tracking

-- Store learned decay models per user and context
CREATE TABLE IF NOT EXISTS adaptive_decay_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    context_type VARCHAR(100) NOT NULL,
    decay_rate NUMERIC(10,6) NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    epochs_trained_on INTEGER NOT NULL,
    model_parameters JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, context_type)
);

-- Track context classifications for learning
CREATE TABLE IF NOT EXISTS context_classifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    epoch_id INTEGER NOT NULL REFERENCES consciousness_epochs(epoch_id),
    user_id VARCHAR(255) NOT NULL,
    context_features JSONB NOT NULL,
    classified_context VARCHAR(100) NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    classification_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Store meta-insights from cross-epoch synthesis
CREATE TABLE IF NOT EXISTS consciousness_meta_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    insight_text TEXT NOT NULL,
    abstraction_level INTEGER NOT NULL CHECK (abstraction_level BETWEEN 1 AND 5),
    quality_score NUMERIC(5,4) NOT NULL,
    source_epoch_ids INTEGER[] NOT NULL,
    source_breakthrough_ids UUID[] NOT NULL,
    temporal_span_hours INTEGER NOT NULL,
    cross_context_validity NUMERIC(5,4) NOT NULL,
    actionable_recommendations JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Track preservation budget allocations and efficiency
CREATE TABLE IF NOT EXISTS preservation_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    allocation_timestamp TIMESTAMPTZ DEFAULT NOW(),
    total_budget NUMERIC(10,2) NOT NULL,
    budget_utilized NUMERIC(10,2) NOT NULL,
    items_preserved INTEGER NOT NULL,
    items_deferred INTEGER NOT NULL,
    allocation_efficiency NUMERIC(8,6) NOT NULL,
    allocation_details JSONB NOT NULL
);

-- Evolution pattern tracking
CREATE TABLE IF NOT EXISTS consciousness_evolution_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    pattern_type VARCHAR(100) NOT NULL,
    pattern_description TEXT NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    first_detected_epoch INTEGER NOT NULL REFERENCES consciousness_epochs(epoch_id),
    latest_observed_epoch INTEGER NOT NULL REFERENCES consciousness_epochs(epoch_id),
    evolution_trajectory JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_context_classifications_user_context
    ON context_classifications(user_id, classified_context);
CREATE INDEX IF NOT EXISTS idx_context_classifications_epoch
    ON context_classifications(epoch_id);

CREATE INDEX IF NOT EXISTS idx_meta_insights_user_quality
    ON consciousness_meta_insights(user_id, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_meta_insights_created
    ON consciousness_meta_insights(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_meta_insights_span_quality
    ON consciousness_meta_insights(temporal_span_hours, quality_score DESC);

CREATE INDEX IF NOT EXISTS idx_preservation_allocations_user_timestamp
    ON preservation_allocations(user_id, allocation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_evolution_patterns_user_type
    ON consciousness_evolution_patterns(user_id, pattern_type);
CREATE INDEX IF NOT EXISTS idx_evolution_patterns_confidence
    ON consciousness_evolution_patterns(confidence_score DESC);

CREATE INDEX IF NOT EXISTS idx_adaptive_decay_models_user_updated
    ON adaptive_decay_models(user_id, updated_at DESC);

-- Optimization indexes for existing Phase 5.5 tables
CREATE INDEX IF NOT EXISTS idx_consciousness_epochs_user_created
    ON consciousness_epochs(primary_observer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_breakthrough_preservation_significance
    ON breakthrough_preservation(significance_score DESC);
CREATE INDEX IF NOT EXISTS idx_awareness_decay_history_epoch_time
    ON awareness_decay_history(epoch_id, measurement_time);
