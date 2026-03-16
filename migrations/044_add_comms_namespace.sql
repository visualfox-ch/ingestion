-- Migration 044: Add unified "comms" namespace
-- Purpose: Single namespace for all chat/comms with origin_namespace tags.

INSERT INTO namespaces (namespace_id, privacy_level, display_name, description)
VALUES
  ('comms', 2, 'Comms', 'Unified communications namespace (filter by origin_namespace/org)')
ON CONFLICT (namespace_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  updated_at = NOW();
