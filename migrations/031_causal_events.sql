-- Phase 19.5B / CK02: Causal Events Schema

CREATE TABLE IF NOT EXISTS causal_events (
    event_id TEXT PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    description TEXT NOT NULL,
    context JSONB,
    related_events JSONB,
    outcome TEXT,
    confidence_score DOUBLE PRECISION DEFAULT 0.5
);

CREATE INDEX IF NOT EXISTS causal_events_type_time_idx
    ON causal_events (event_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS causal_events_actor_time_idx
    ON causal_events (actor, timestamp DESC);
