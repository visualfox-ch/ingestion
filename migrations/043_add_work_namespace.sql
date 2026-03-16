-- Migration 043: Add umbrella "work" namespace
-- Purpose: Introduce work namespace while keeping legacy namespaces intact.

INSERT INTO namespaces (namespace_id, privacy_level, display_name, description)
VALUES
  ('work', 2, 'Work', 'Umbrella work namespace (projektil + visualfox)')
ON CONFLICT (namespace_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  updated_at = NOW();
