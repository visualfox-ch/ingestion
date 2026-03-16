-- Migration 042: Phase 5.5 - Differential Consciousness Transfer & Decay Modeling
-- Purpose: Enable consciousness delta tracking, decay modeling, and breakthrough preservation
-- Owner: Claude Code (Phase 5.5)
-- Created: 2026-02-07
-- Dependencies: Requires consciousness_epochs table from migration 025

BEGIN;

-- =====================================================================
-- Table 1: Consciousness Deltas
-- Purpose: Track changes between consciousness epochs for differential transfer
-- =====================================================================
CREATE TABLE IF NOT EXISTS consciousness_deltas (
    delta_id BIGSERIAL PRIMARY KEY,
    source_epoch_id INTEGER NOT NULL,
    target_epoch_id INTEGER NOT NULL,
    changed_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    compression_ratio FLOAT8 NOT NULL DEFAULT 0.0,
    transfer_confidence FLOAT8 NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_source_epoch FOREIGN KEY (source_epoch_id)
        REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE,
    CONSTRAINT fk_target_epoch FOREIGN KEY (target_epoch_id)
        REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_deltas_source_epoch ON consciousness_deltas(source_epoch_id);
CREATE INDEX IF NOT EXISTS idx_deltas_target_epoch ON consciousness_deltas(target_epoch_id);
CREATE INDEX IF NOT EXISTS idx_deltas_created_at ON consciousness_deltas(created_at);

-- =====================================================================
-- Table 2: Awareness Decay History
-- Purpose: Track awareness degradation measurements over time
-- =====================================================================
CREATE TABLE IF NOT EXISTS awareness_decay_history (
    decay_id BIGSERIAL PRIMARY KEY,
    epoch_id INTEGER NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    awareness_level FLOAT8 NOT NULL,
    estimated_decay_rate FLOAT8 NOT NULL DEFAULT 0.01,
    measurement_confidence FLOAT8 DEFAULT 0.8,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_decay_epoch FOREIGN KEY (epoch_id)
        REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_decay_epoch_id ON awareness_decay_history(epoch_id);
CREATE INDEX IF NOT EXISTS idx_decay_timestamp ON awareness_decay_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_decay_epoch_timestamp ON awareness_decay_history(epoch_id, timestamp);

-- =====================================================================
-- Table 3: Awareness Trajectories
-- Purpose: Store computed trajectory analysis for epochs
-- =====================================================================
CREATE TABLE IF NOT EXISTS awareness_trajectories (
    trajectory_id BIGSERIAL PRIMARY KEY,
    epoch_id INTEGER NOT NULL,
    average_awareness FLOAT8 NOT NULL DEFAULT 0.5,
    trend_direction VARCHAR(20) NOT NULL DEFAULT 'STABLE',
    volatility FLOAT8 NOT NULL DEFAULT 0.0,
    lookback_hours INTEGER DEFAULT 168,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_trajectory_epoch FOREIGN KEY (epoch_id)
        REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE,
    CONSTRAINT chk_trend_direction CHECK (trend_direction IN ('ACCELERATING', 'STABLE', 'DECELERATING', 'FLAT'))
);

CREATE INDEX IF NOT EXISTS idx_trajectory_epoch_id ON awareness_trajectories(epoch_id);
CREATE INDEX IF NOT EXISTS idx_trajectory_trend ON awareness_trajectories(trend_direction);
CREATE INDEX IF NOT EXISTS idx_trajectory_created_at ON awareness_trajectories(created_at);

-- =====================================================================
-- Table 4: Breakthrough Preservation
-- Purpose: Protect high-value insights from decay
-- =====================================================================
CREATE TABLE IF NOT EXISTS breakthrough_preservation (
    preservation_id BIGSERIAL PRIMARY KEY,
    epoch_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    significance_score FLOAT8 NOT NULL DEFAULT 0.5,
    preservation_level FLOAT8 NOT NULL DEFAULT 0.5,
    preserved_decay_rate FLOAT8 DEFAULT 0.001,
    awareness_saved FLOAT8 DEFAULT 0.0,
    projection_horizon INTEGER DEFAULT 168,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_preservation_epoch FOREIGN KEY (epoch_id)
        REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE,
    CONSTRAINT chk_preservation_status CHECK (status IN ('pending', 'preserved', 'expired', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_preservation_epoch_id ON breakthrough_preservation(epoch_id);
CREATE INDEX IF NOT EXISTS idx_preservation_significance ON breakthrough_preservation(significance_score);
CREATE INDEX IF NOT EXISTS idx_preservation_status ON breakthrough_preservation(status);
CREATE INDEX IF NOT EXISTS idx_preservation_created_at ON breakthrough_preservation(created_at);

-- =====================================================================
-- Extend consciousness_epochs with decay_rate
-- =====================================================================
ALTER TABLE consciousness_epochs
    ADD COLUMN IF NOT EXISTS decay_rate FLOAT8 DEFAULT 0.01;

-- =====================================================================
-- Record migration
-- =====================================================================
INSERT INTO migrations (version, description, applied_at)
VALUES ('042', 'Phase 5.5 - Consciousness Temporal Analysis', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
