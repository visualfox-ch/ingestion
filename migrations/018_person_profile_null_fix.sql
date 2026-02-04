-- Migration 018: Fix person_profile.current_version_id NULL issue
-- Problem: Profiles with NULL current_version_id are invisible to get_person_profile()
-- when approved_only=True, because NULL != 'approved' is always True
--
-- Jarvis Impact: "Ich kenne Leute nicht die ich kennen sollte"
-- Created: 2026-02-02
-- Owner: Claude (Data Pipeline Consistency Fixes)

BEGIN;

-- Step 1: Create initial versions for profiles that have NO versions at all
-- These profiles were created but never got a version entry
INSERT INTO person_profile_version (
    profile_id,
    version_number,
    content,
    changed_by,
    change_reason,
    change_type,
    status,
    created_at
)
SELECT
    p.id,
    1,  -- First version
    COALESCE(
        -- Try to build content from existing profile data
        jsonb_build_object(
            'name', p.name,
            'org', p.org,
            'profile_type', p.profile_type,
            'languages', p.languages,
            'timezone', p.timezone
        ),
        '{}'::jsonb
    ),
    'system_migration_018',
    'Auto-created initial version during migration 018 (NULL fix)',
    'initial',
    'approved',  -- Auto-approve these legacy profiles
    p.created_at  -- Use original profile creation time
FROM person_profile p
WHERE NOT EXISTS (
    SELECT 1 FROM person_profile_version v WHERE v.profile_id = p.id
);

-- Step 2: Update profiles to point to their newest approved version
-- (or newest version if none approved)
UPDATE person_profile p
SET current_version_id = (
    SELECT v.id
    FROM person_profile_version v
    WHERE v.profile_id = p.id
    ORDER BY
        CASE WHEN v.status = 'approved' THEN 0 ELSE 1 END,
        v.version_number DESC
    LIMIT 1
)
WHERE p.current_version_id IS NULL;

-- Step 3: Verify no NULL values remain
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM person_profile
    WHERE current_version_id IS NULL;

    IF null_count > 0 THEN
        RAISE WARNING 'Migration 018: % profiles still have NULL current_version_id', null_count;
    ELSE
        RAISE NOTICE 'Migration 018: All profiles now have current_version_id set';
    END IF;
END $$;

-- Step 4: Add constraint to prevent future NULLs (commented out - enable after verification)
-- Note: Uncomment only after verifying all profiles have versions
-- ALTER TABLE person_profile ALTER COLUMN current_version_id SET NOT NULL;

COMMIT;

-- Verification query (run manually):
-- SELECT p.person_id, p.name, p.current_version_id, v.status as version_status
-- FROM person_profile p
-- LEFT JOIN person_profile_version v ON p.current_version_id = v.id
-- WHERE p.current_version_id IS NULL OR v.status IS NULL;
