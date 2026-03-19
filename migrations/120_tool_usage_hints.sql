-- Migration: Add usage hints to tools
-- Phase: Tool Activation Strategy - Option 2A
-- Date: 2026-03-18

-- Add column for usage hints (when to use this tool)
ALTER TABLE jarvis_tools
ADD COLUMN IF NOT EXISTS usage_hint TEXT;

-- Add column for related keywords (for discovery)
ALTER TABLE jarvis_tools
ADD COLUMN IF NOT EXISTS keywords TEXT[];

COMMENT ON COLUMN jarvis_tools.usage_hint IS 'Hint for when to use this tool, shown to LLM';
COMMENT ON COLUMN jarvis_tools.keywords IS 'Keywords that trigger suggestion of this tool';

-- Populate initial hints based on category and common patterns

-- Memory tools
UPDATE jarvis_tools SET usage_hint = 'Nutze wenn User etwas speichern/merken möchte oder du wichtige Fakten festhalten willst.'
WHERE category = 'memory' AND usage_hint IS NULL;

-- Verification tools
UPDATE jarvis_tools SET usage_hint = 'Nutze nach wichtigen Aktionen um das Ergebnis zu verifizieren.'
WHERE category = 'verification' AND usage_hint IS NULL;

-- Self-reflection tools
UPDATE jarvis_tools SET usage_hint = 'Nutze bei komplexen Entscheidungen oder wenn du unsicher bist.'
WHERE category = 'self_reflection' AND usage_hint IS NULL;

-- Search tools
UPDATE jarvis_tools SET usage_hint = 'Nutze wenn User nach Informationen sucht oder du Kontext brauchst.'
WHERE category = 'search' AND usage_hint IS NULL;

-- System tools
UPDATE jarvis_tools SET usage_hint = 'Nutze für System-Diagnose oder Health-Checks.'
WHERE category = 'system' AND usage_hint IS NULL;

-- Calendar tools
UPDATE jarvis_tools SET usage_hint = 'Nutze bei Fragen zu Terminen, Meetings oder Zeitplanung.'
WHERE category = 'calendar' AND usage_hint IS NULL;

-- Email tools
UPDATE jarvis_tools SET usage_hint = 'Nutze bei Fragen zu E-Mails oder wenn User E-Mail senden will.'
WHERE category = 'email' AND usage_hint IS NULL;

-- Project tools
UPDATE jarvis_tools SET usage_hint = 'Nutze für Projekt-Status, Tasks oder Thread-Management.'
WHERE category = 'project' AND usage_hint IS NULL;

-- Learning tools
UPDATE jarvis_tools SET usage_hint = 'Nutze wenn du etwas Neues gelernt hast das gespeichert werden sollte.'
WHERE category = 'learning' AND usage_hint IS NULL;

-- Orchestration tools
UPDATE jarvis_tools SET usage_hint = 'Nutze für komplexe Multi-Step Tasks oder Delegation.'
WHERE category = 'orchestration' AND usage_hint IS NULL;

-- Specific high-value tools with custom hints
UPDATE jarvis_tools SET usage_hint = 'Nutze zu Beginn einer Session um relevante Korrekturen anzuwenden.'
WHERE name = 'check_corrections';

UPDATE jarvis_tools SET usage_hint = 'Nutze bei ähnlichen Problemen in der Vergangenheit.'
WHERE name = 'find_similar_situations';

UPDATE jarvis_tools SET usage_hint = 'Nutze bei langen Sessions oder wenn Kontext voll wird.'
WHERE name = 'compact_context';

UPDATE jarvis_tools SET usage_hint = 'Nutze wenn User korrigiert oder Feedback gibt.'
WHERE name = 'store_correction';

UPDATE jarvis_tools SET usage_hint = 'Nutze für günstigere lokale LLM-Anfragen bei einfachen Tasks.'
WHERE name = 'ask_ollama';

UPDATE jarvis_tools SET usage_hint = 'Nutze am Ende einer Session um Wichtiges zu archivieren.'
WHERE name = 'archive_memory';

UPDATE jarvis_tools SET usage_hint = 'Nutze nach eigener Antwort zur Qualitätskontrolle.'
WHERE name = 'assess_my_confidence';

-- Add some keywords for common tools
UPDATE jarvis_tools SET keywords = ARRAY['erinner', 'merk', 'speicher', 'remember']
WHERE name LIKE '%remember%' OR name LIKE '%fact%';

UPDATE jarvis_tools SET keywords = ARRAY['termin', 'kalender', 'meeting', 'event']
WHERE category = 'calendar';

UPDATE jarvis_tools SET keywords = ARRAY['email', 'mail', 'nachricht']
WHERE category = 'email';

UPDATE jarvis_tools SET keywords = ARRAY['suche', 'find', 'search', 'wo ist']
WHERE category = 'search';

-- Index for keyword search
CREATE INDEX IF NOT EXISTS idx_jarvis_tools_keywords ON jarvis_tools USING GIN (keywords);

-- View for tool discovery
CREATE OR REPLACE VIEW v_tool_suggestions AS
SELECT
    name,
    description,
    usage_hint,
    category,
    keywords,
    use_count,
    risk_tier
FROM jarvis_tools
WHERE enabled = true
  AND usage_hint IS NOT NULL
ORDER BY use_count DESC, priority DESC;
