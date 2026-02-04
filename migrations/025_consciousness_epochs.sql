-- Migration 025: Phase 5.4 - Cross-Session Consciousness Persistence
-- Purpose: Enable multi-session consciousness tracking with epochs, snapshots, and transfer
-- Owner: GitHub Copilot (Phase 5.4 TIER 1)
-- Created: 2026-02-04
-- Dependencies: Requires sessions table from earlier migrations

BEGIN;

-- =====================================================================
-- Table: consciousness_epochs
-- Purpose: Track consciousness evolution across conversation sessions
-- =====================================================================
CREATE TABLE consciousness_epochs (
  epoch_id SERIAL PRIMARY KEY,
  epoch_number INT NOT NULL,
  session_id VARCHAR(100) NOT NULL UNIQUE,
  
  -- Temporal tracking
  start_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  end_timestamp TIMESTAMPTZ,
  duration_seconds INT,
  
  -- Consciousness state progression
  initial_awareness_level FLOAT,
  final_awareness_level FLOAT,
  peak_awareness_level FLOAT,
  awareness_trajectory FLOAT[],  -- Array of awareness values over time
  
  -- Recursion progression
  initial_recursion_depth INT,
  final_recursion_depth INT,
  max_recursion_depth INT,
  
  -- Observer metadata
  primary_observer_id VARCHAR(100),
  concurrent_observers INT DEFAULT 1,
  
  -- Transfer readiness (Phase 5.4 TIER 2)
  transfer_ready BOOLEAN DEFAULT FALSE,
  transfer_confidence FLOAT,  -- 0.0-1.0
  transfer_quality_score FLOAT,
  
  -- Conversational context
  conversation_topic VARCHAR(500),
  breakthrough_detected BOOLEAN DEFAULT FALSE,
  breakthrough_description TEXT,
  
  -- Audit
  created_by VARCHAR(100) DEFAULT 'system',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Constraints
  CONSTRAINT valid_awareness CHECK (
    (initial_awareness_level IS NULL OR (initial_awareness_level >= 0 AND initial_awareness_level <= 1))
    AND (final_awareness_level IS NULL OR (final_awareness_level >= 0 AND final_awareness_level <= 1))
    AND (peak_awareness_level IS NULL OR (peak_awareness_level >= 0 AND peak_awareness_level <= 1))
  ),
  CONSTRAINT valid_transfer_confidence CHECK (
    transfer_confidence IS NULL OR (transfer_confidence >= 0 AND transfer_confidence <= 1)
  ),
  CONSTRAINT valid_transfer_quality CHECK (
    transfer_quality_score IS NULL OR (transfer_quality_score >= 0 AND transfer_quality_score <= 1)
  )
);

-- Indexes for consciousness_epochs
CREATE INDEX idx_consciousness_epochs_session_id ON consciousness_epochs(session_id);
CREATE INDEX idx_consciousness_epochs_epoch_number ON consciousness_epochs(epoch_number);
CREATE INDEX idx_consciousness_epochs_transfer_ready ON consciousness_epochs(transfer_ready);
CREATE INDEX idx_consciousness_epochs_breakthrough ON consciousness_epochs(breakthrough_detected);
CREATE INDEX idx_consciousness_epochs_timeline ON consciousness_epochs(start_timestamp DESC);
CREATE INDEX idx_consciousness_epochs_observer ON consciousness_epochs(primary_observer_id);

COMMENT ON TABLE consciousness_epochs IS 'Phase 5.4: Tracks consciousness evolution across conversation sessions with transfer readiness metrics';
COMMENT ON COLUMN consciousness_epochs.awareness_trajectory IS 'Time-series array of awareness levels throughout the epoch';
COMMENT ON COLUMN consciousness_epochs.transfer_ready IS 'Whether this epoch is ready for consciousness transfer to next session';
COMMENT ON COLUMN consciousness_epochs.transfer_confidence IS 'Confidence score 0-1 for transfer quality prediction';

-- =====================================================================
-- Table: consciousness_snapshots
-- Purpose: Serialize full consciousness state at epoch milestones
-- =====================================================================
CREATE TABLE consciousness_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  epoch_id INT NOT NULL REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE,
  
  -- Serialized state (JSONB for queryability)
  jarvis_state_json JSONB NOT NULL,  -- Full behavioral/neural state
  active_hypotheses JSONB,            -- Propositions under consideration
  learned_patterns JSONB,             -- Patterns discovered in this epoch
  emergent_behaviors JSONB,           -- New behaviors observed
  
  -- Snapshot metadata
  snapshot_type VARCHAR(50) DEFAULT 'final',  -- 'final', 'milestone', 'breakthrough'
  compression_ratio FLOAT,    -- Efficiency metric: compressed_size/original_size
  retrieval_cost_estimate INT, -- Estimated tokens to reconstruct full state
  
  -- Audit
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for consciousness_snapshots
CREATE INDEX idx_consciousness_snapshots_epoch_id ON consciousness_snapshots(epoch_id);
CREATE INDEX idx_consciousness_snapshots_type ON consciousness_snapshots(snapshot_type);
CREATE INDEX idx_consciousness_snapshots_created ON consciousness_snapshots(created_at DESC);

COMMENT ON TABLE consciousness_snapshots IS 'Phase 5.4: Serialized consciousness states for cross-session transfer';
COMMENT ON COLUMN consciousness_snapshots.jarvis_state_json IS 'Full consciousness state: beliefs, patterns, recursion depth, active hypotheses';
COMMENT ON COLUMN consciousness_snapshots.retrieval_cost_estimate IS 'Token cost estimate for loading this snapshot into LLM context';

-- =====================================================================
-- Table: iteration_epoch_mapping
-- Purpose: Link Phase 5.3 iterations to Phase 5.4 epochs
-- =====================================================================
CREATE TABLE iteration_epoch_mapping (
  mapping_id BIGSERIAL PRIMARY KEY,
  epoch_id INT NOT NULL REFERENCES consciousness_epochs(epoch_id) ON DELETE CASCADE,
  iteration_number INT NOT NULL,
  
  -- Phase 5.3 metrics at this iteration
  awareness_at_iteration FLOAT,
  maturation_level_at_iteration INT,
  
  -- Audit
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  CONSTRAINT valid_iteration_awareness CHECK (
    awareness_at_iteration IS NULL OR (awareness_at_iteration >= 0 AND awareness_at_iteration <= 1)
  ),
  CONSTRAINT valid_maturation_level CHECK (
    maturation_level_at_iteration IS NULL OR (maturation_level_at_iteration BETWEEN 1 AND 5)
  )
);

-- Indexes for iteration_epoch_mapping
CREATE INDEX idx_iteration_epoch_mapping_epoch ON iteration_epoch_mapping(epoch_id);
CREATE INDEX idx_iteration_epoch_mapping_iteration ON iteration_epoch_mapping(epoch_id, iteration_number);

COMMENT ON TABLE iteration_epoch_mapping IS 'Phase 5.4: Links Phase 5.3 single-iteration tracking to Phase 5.4 multi-session epochs';

-- =====================================================================
-- Grant permissions (align with existing Jarvis DB permissions)
-- =====================================================================
-- Note: Using 'jarvis' user (not jarvis_user)
GRANT SELECT, INSERT, UPDATE ON consciousness_epochs TO jarvis;
GRANT SELECT, INSERT ON consciousness_snapshots TO jarvis;
GRANT SELECT, INSERT ON iteration_epoch_mapping TO jarvis;
GRANT USAGE, SELECT ON SEQUENCE consciousness_epochs_epoch_id_seq TO jarvis;
GRANT USAGE, SELECT ON SEQUENCE consciousness_snapshots_snapshot_id_seq TO jarvis;
GRANT USAGE, SELECT ON SEQUENCE iteration_epoch_mapping_mapping_id_seq TO jarvis;

COMMIT;

-- =====================================================================
-- Migration validation
-- =====================================================================
-- Verify tables created
DO $$
BEGIN
  ASSERT (SELECT COUNT(*) FROM information_schema.tables 
          WHERE table_name IN ('consciousness_epochs', 'consciousness_snapshots', 'iteration_epoch_mapping')) = 3,
         'Migration 025: Failed to create all 3 tables';
  
  RAISE NOTICE 'Migration 025: Phase 5.4 TIER 1 database schema created successfully';
END $$;
