-- Migration 132: Message Queue & Request/Response (Phase 22B-02, 22B-03)
-- Async message queue and sync request/response patterns

-- Message Queue table
CREATE TABLE IF NOT EXISTS jarvis_message_queue (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(50) UNIQUE NOT NULL,
    queue_name VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    priority INTEGER DEFAULT 3,
    state VARCHAR(20) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    visibility_timeout TIMESTAMP,
    scheduled_at TIMESTAMP,
    processed_at TIMESTAMP,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Dead Letter Queue
CREATE TABLE IF NOT EXISTS jarvis_dead_letter_queue (
    id SERIAL PRIMARY KEY,
    original_message_id VARCHAR(50),
    queue_name VARCHAR(50),
    payload JSONB,
    error TEXT,
    retry_count INTEGER,
    original_created_at TIMESTAMP,
    moved_at TIMESTAMP DEFAULT NOW()
);

-- Agent Requests table (for request/response tracking)
CREATE TABLE IF NOT EXISTS jarvis_agent_requests (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(50) UNIQUE NOT NULL,
    correlation_id VARCHAR(50),
    from_agent VARCHAR(50) NOT NULL,
    to_agent VARCHAR(50) NOT NULL,
    method VARCHAR(100) NOT NULL,
    params JSONB DEFAULT '{}',
    timeout_ms INTEGER DEFAULT 30000,
    state VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    error TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Circuit Breakers table
CREATE TABLE IF NOT EXISTS jarvis_circuit_breakers (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50) UNIQUE NOT NULL,
    state VARCHAR(20) DEFAULT 'closed',
    failure_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    threshold INTEGER DEFAULT 5,
    reset_timeout_seconds INTEGER DEFAULT 60,
    last_failure_at TIMESTAMP,
    last_success_at TIMESTAMP,
    last_state_change TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mq_queue_state ON jarvis_message_queue(queue_name, state, priority, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_mq_visibility ON jarvis_message_queue(visibility_timeout) WHERE state = 'processing';
CREATE INDEX IF NOT EXISTS idx_dlq_queue ON jarvis_dead_letter_queue(queue_name);
CREATE INDEX IF NOT EXISTS idx_requests_state ON jarvis_agent_requests(state, created_at);
CREATE INDEX IF NOT EXISTS idx_requests_correlation ON jarvis_agent_requests(correlation_id) WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_requests_agents ON jarvis_agent_requests(from_agent, to_agent);

-- Comments
COMMENT ON TABLE jarvis_message_queue IS 'Phase 22B-02: Async message queue for agents';
COMMENT ON TABLE jarvis_dead_letter_queue IS 'Phase 22B-02: Failed messages after max retries';
COMMENT ON TABLE jarvis_agent_requests IS 'Phase 22B-03: Sync request/response tracking';
COMMENT ON TABLE jarvis_circuit_breakers IS 'Phase 22B-03: Circuit breaker state per agent';
