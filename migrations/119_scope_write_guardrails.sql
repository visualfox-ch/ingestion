-- Migration 119: Hard Scope Write Guardrails
--
-- Ziel:
-- 1) Neue Writes mit namespace sollen automatisch passende scope_* Felder erhalten.
-- 2) Inkonsistente namespace/scope Kombinationen werden geblockt.
-- 3) Writes mit namespace aber ohne scope_org/scope_visibility werden DB-seitig verhindert.
--
-- Voraussetzung: scope_alias_resolution ist gepflegt.

-- Generic trigger for tables with namespace + scope columns.
CREATE OR REPLACE FUNCTION apply_and_validate_scope_from_namespace()
RETURNS TRIGGER AS $$
DECLARE
    m RECORD;
    has_domain BOOLEAN := FALSE;
BEGIN
    IF TG_NARGS > 0 AND TG_ARGV[0] = 'has_domain' THEN
        has_domain := TRUE;
    END IF;

    -- No namespace => no namespace->scope enforcement on this row.
    IF NEW.namespace IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT target_org, target_visibility, target_domain
      INTO m
      FROM scope_alias_resolution
     WHERE legacy_namespace IS NOT DISTINCT FROM NEW.namespace
     LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No scope alias mapping for namespace=%', NEW.namespace
            USING ERRCODE = 'check_violation';
    END IF;

    -- Autofill missing scope values from alias mapping.
    IF NEW.scope_org IS NULL THEN
        NEW.scope_org := m.target_org;
    END IF;

    IF NEW.scope_visibility IS NULL THEN
        NEW.scope_visibility := m.target_visibility;
    END IF;

    IF has_domain AND NEW.scope_domain IS NULL THEN
        NEW.scope_domain := m.target_domain;
    END IF;

    -- Hard consistency checks against mapping.
    IF NEW.scope_org IS DISTINCT FROM m.target_org
       OR NEW.scope_visibility IS DISTINCT FROM m.target_visibility THEN
        RAISE EXCEPTION
            'Scope mismatch for namespace=% (expected %/% but got %/%)',
            NEW.namespace,
            m.target_org,
            m.target_visibility,
            NEW.scope_org,
            NEW.scope_visibility
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t RECORD;
    trg_name TEXT;
    constraint_name TEXT;
BEGIN
    FOR t IN
        SELECT *
        FROM (VALUES
            ('connector_state', FALSE),
            ('ingest_event', TRUE),
            ('conversation', FALSE),
            ('decision_logs', FALSE),
            ('learned_facts', FALSE),
            ('memory_facts_layered', FALSE),
            ('upload_queue', TRUE),
            ('interaction_quality', FALSE),
            ('knowledge_item', TRUE),
            ('chat_sync_state', FALSE),
            ('entity_mentions', FALSE),
            ('pattern_history', FALSE),
            ('prompt_fragment', FALSE),
            ('conversation_context', FALSE),
            ('person_channel_preference', FALSE),
            ('person_relationship', FALSE),
            ('hygiene_baselines', FALSE),
            ('knowledge_evidence_link', FALSE)
        ) AS x(table_name, has_domain)
    LOOP
        trg_name := 'trg_' || t.table_name || '_scope_guard';

        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', trg_name, t.table_name);

        IF t.has_domain THEN
            EXECUTE format(
                'CREATE TRIGGER %I
                   BEFORE INSERT OR UPDATE OF namespace, scope_org, scope_visibility, scope_domain
                   ON %I
                   FOR EACH ROW
                   EXECUTE FUNCTION apply_and_validate_scope_from_namespace(''has_domain'')',
                trg_name,
                t.table_name
            );
        ELSE
            EXECUTE format(
                'CREATE TRIGGER %I
                   BEFORE INSERT OR UPDATE OF namespace, scope_org, scope_visibility
                   ON %I
                   FOR EACH ROW
                   EXECUTE FUNCTION apply_and_validate_scope_from_namespace()',
                trg_name,
                t.table_name
            );
        END IF;

        -- Hard check constraint: namespace implies scope org+visibility present.
        constraint_name := t.table_name || '_namespace_requires_scope_chk';
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint c
              JOIN pg_class rel ON rel.oid = c.conrelid
             WHERE rel.relname = t.table_name
               AND c.conname = constraint_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I
                 ADD CONSTRAINT %I
                 CHECK (namespace IS NULL OR (scope_org IS NOT NULL AND scope_visibility IS NOT NULL))',
                t.table_name,
                constraint_name
            );
        END IF;

        EXECUTE format('ALTER TABLE %I VALIDATE CONSTRAINT %I', t.table_name, constraint_name);
    END LOOP;
END;
$$;

COMMENT ON FUNCTION apply_and_validate_scope_from_namespace() IS
    'DB guardrail for namespace->scope migration: autofill scope from alias map and block mismatches.';
