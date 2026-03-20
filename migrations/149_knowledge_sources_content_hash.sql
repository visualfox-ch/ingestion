-- Migration 149: Add content_hash to knowledge_sources
-- Enables incremental ingest: skip re-embedding when source file unchanged.
ALTER TABLE knowledge_sources
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

COMMENT ON COLUMN knowledge_sources.content_hash IS
    'SHA-256 hex digest of the source file content at last successful ingest. NULL = never ingested or hash not computed.';
