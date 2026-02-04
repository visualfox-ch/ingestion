-- Phase 18.x: Person Entity Search + Evidence Linking
-- Migration: 017_person_entity_upgrade.sql
-- Created: 2026-02-02
-- Author: GitHub Copilot

-- =============================================================================
-- EXTENSIONS
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- PERSON PROFILE CORE FIELDS (SEARCH INTEGRATION)
-- =============================================================================
ALTER TABLE person_profile
    ADD COLUMN IF NOT EXISTS first_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS last_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS birthday DATE,
    ADD COLUMN IF NOT EXISTS primary_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS aliases JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_person_profile_name ON person_profile(name);
CREATE INDEX IF NOT EXISTS idx_person_profile_first_name ON person_profile(first_name);
CREATE INDEX IF NOT EXISTS idx_person_profile_last_name ON person_profile(last_name);
CREATE INDEX IF NOT EXISTS idx_person_profile_birthday ON person_profile(birthday);
CREATE INDEX IF NOT EXISTS idx_person_profile_email ON person_profile(primary_email);

-- =============================================================================
-- PERSON PROFILE VERSION VALIDATION STATE
-- =============================================================================
ALTER TABLE person_profile_version
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(50) DEFAULT 'tbc',
    ADD COLUMN IF NOT EXISTS validation_note TEXT,
    ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ppv_validation_status ON person_profile_version(validation_status);

-- =============================================================================
-- PERSON IDENTIFIERS (ALIAS/NAME SEARCH)
-- =============================================================================
CREATE TABLE IF NOT EXISTS person_identifier (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id VARCHAR(100) NOT NULL,
    identifier_type VARCHAR(50) NOT NULL, -- first_name|last_name|full_name|email|birthday|alias|org
    identifier_value VARCHAR(255) NOT NULL,
    normalized_value VARCHAR(255),
    confidence DECIMAL(3,2) DEFAULT 0.50,
    status VARCHAR(50) DEFAULT 'tbc', -- tbc|validated|confirmed|disputed|obsolete
    evidence_sources JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(person_id, identifier_type, identifier_value)
);

CREATE INDEX IF NOT EXISTS idx_person_identifier_person ON person_identifier(person_id);
CREATE INDEX IF NOT EXISTS idx_person_identifier_type ON person_identifier(identifier_type);
CREATE INDEX IF NOT EXISTS idx_person_identifier_value ON person_identifier(identifier_value);
CREATE INDEX IF NOT EXISTS idx_person_identifier_normalized ON person_identifier(normalized_value);
CREATE INDEX IF NOT EXISTS idx_person_identifier_status ON person_identifier(status);

-- =============================================================================
-- PERSON OBSERVATIONS (TBC / VALIDATION PIPELINE)
-- =============================================================================
CREATE TABLE IF NOT EXISTS person_observation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id VARCHAR(100) NOT NULL,
    field_path VARCHAR(200) NOT NULL, -- e.g. "relationship.role", "preferences.style"
    observed_value TEXT,
    confidence DECIMAL(3,2) DEFAULT 0.50,
    validation_status VARCHAR(50) DEFAULT 'tbc', -- tbc|validated|confirmed|disputed|obsolete
    evidence_refs JSONB,
    first_observed_at TIMESTAMPTZ DEFAULT NOW(),
    last_observed_at TIMESTAMPTZ DEFAULT NOW(),
    last_validated_at TIMESTAMPTZ,
    source_type VARCHAR(50),
    source_id VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_person_observation_person ON person_observation(person_id);
CREATE INDEX IF NOT EXISTS idx_person_observation_field ON person_observation(field_path);
CREATE INDEX IF NOT EXISTS idx_person_observation_status ON person_observation(validation_status);

-- =============================================================================
-- EVIDENCE LINKING (GENERIC)
-- =============================================================================
CREATE TABLE IF NOT EXISTS knowledge_evidence_link (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_type VARCHAR(50) NOT NULL, -- profile_version|insight_note|memory|other
    item_id VARCHAR(100) NOT NULL,
    evidence_type VARCHAR(50) NOT NULL, -- chat|email|document|qdrant|manual
    evidence_ref VARCHAR(255),
    source_path TEXT,
    namespace VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_evidence_item ON knowledge_evidence_link(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_evidence_ref ON knowledge_evidence_link(evidence_ref);

-- =============================================================================
-- OPTIONAL: BACKFILL IDENTIFIERS FROM EXISTING PERSON_PROFILE
-- =============================================================================
-- INSERT INTO person_identifier (person_id, identifier_type, identifier_value, normalized_value, confidence, status)
-- SELECT person_id, 'full_name', name, lower(name), 0.7, 'tbc'
-- FROM person_profile
-- WHERE name IS NOT NULL
-- ON CONFLICT DO NOTHING;
