-- Migration: 096_smart_home_integration.sql
-- Purpose: Smart Home / Home Assistant integration tables
-- Date: 2026-03-14

-- Smart Home device cache (synced from Home Assistant)
CREATE TABLE IF NOT EXISTS smart_home_devices (
    id SERIAL PRIMARY KEY,
    entity_id VARCHAR(255) UNIQUE NOT NULL,
    friendly_name VARCHAR(255),
    device_type VARCHAR(50) NOT NULL,
    area VARCHAR(100),
    manufacturer VARCHAR(100),
    model VARCHAR(100),
    is_favorite BOOLEAN DEFAULT FALSE,
    is_hidden BOOLEAN DEFAULT FALSE,
    custom_name VARCHAR(255),
    last_state VARCHAR(100),
    last_synced_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Smart Home action log (all commands sent to HA)
CREATE TABLE IF NOT EXISTS smart_home_actions (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(50) NOT NULL,
    service VARCHAR(100) NOT NULL,
    entity_id VARCHAR(255),
    data TEXT,
    success BOOLEAN DEFAULT TRUE,
    error TEXT,
    triggered_by VARCHAR(50) DEFAULT 'jarvis',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Smart Home state history (for pattern detection)
CREATE TABLE IF NOT EXISTS smart_home_state_history (
    id SERIAL PRIMARY KEY,
    entity_id VARCHAR(255) NOT NULL,
    old_state VARCHAR(100),
    new_state VARCHAR(100),
    attributes JSONB,
    changed_at TIMESTAMP DEFAULT NOW()
);

-- Smart Home automations (user-defined via Jarvis)
CREATE TABLE IF NOT EXISTS smart_home_automations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    trigger_type VARCHAR(50) NOT NULL,  -- time, state_change, voice_command, etc.
    trigger_config JSONB NOT NULL,
    action_type VARCHAR(50) NOT NULL,   -- service_call, scene, script
    action_config JSONB NOT NULL,
    conditions JSONB,
    is_enabled BOOLEAN DEFAULT TRUE,
    last_triggered_at TIMESTAMP,
    trigger_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Smart Home scenes (user-defined quick actions)
CREATE TABLE IF NOT EXISTS smart_home_scenes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    actions JSONB NOT NULL,  -- Array of {entity_id, service, data}
    voice_triggers TEXT[],   -- "good night", "movie time", etc.
    is_favorite BOOLEAN DEFAULT FALSE,
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Smart Home user preferences
CREATE TABLE IF NOT EXISTS smart_home_preferences (
    id SERIAL PRIMARY KEY,
    preference_key VARCHAR(100) UNIQUE NOT NULL,
    preference_value JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Insert default preferences
INSERT INTO smart_home_preferences (preference_key, preference_value, description) VALUES
    ('default_light_brightness', '{"value": 200}', 'Default brightness for lights (0-255)'),
    ('default_color_temp', '{"value": 370}', 'Default color temperature (mireds)'),
    ('comfort_temperature', '{"heating": 21.0, "cooling": 24.0}', 'Comfort temperature settings'),
    ('night_mode_start', '{"hour": 22, "minute": 0}', 'Night mode start time'),
    ('night_mode_end', '{"hour": 7, "minute": 0}', 'Night mode end time'),
    ('areas_priority', '{"order": ["living_room", "bedroom", "kitchen", "office"]}', 'Area priority for suggestions')
ON CONFLICT (preference_key) DO NOTHING;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_smart_home_devices_type ON smart_home_devices(device_type);
CREATE INDEX IF NOT EXISTS idx_smart_home_devices_area ON smart_home_devices(area);
CREATE INDEX IF NOT EXISTS idx_smart_home_actions_created ON smart_home_actions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_smart_home_actions_entity ON smart_home_actions(entity_id);
CREATE INDEX IF NOT EXISTS idx_smart_home_state_history_entity ON smart_home_state_history(entity_id);
CREATE INDEX IF NOT EXISTS idx_smart_home_state_history_changed ON smart_home_state_history(changed_at DESC);

-- Add smart_home tools to jarvis_tools
INSERT INTO jarvis_tools (name, description, category, is_enabled, requires_approval, parameters, keywords) VALUES
    ('control_smart_home', 'Control smart home devices (lights, switches, climate)', 'smart_home', TRUE, FALSE,
     '{"entity_id": "string", "action": "turn_on|turn_off|toggle|set", "value": "optional"}',
     ARRAY['licht', 'lampe', 'schalter', 'heizung', 'thermostat', 'light', 'switch', 'turn on', 'turn off', 'einschalten', 'ausschalten']),
    ('get_smart_home_status', 'Get status of smart home devices', 'smart_home', TRUE, FALSE,
     '{"entity_id": "optional string", "device_type": "optional string", "area": "optional string"}',
     ARRAY['status', 'zustand', 'device', 'geraet', 'smart home', 'home assistant']),
    ('list_smart_home_devices', 'List available smart home devices', 'smart_home', TRUE, FALSE,
     '{"device_type": "optional string", "area": "optional string"}',
     ARRAY['devices', 'geraete', 'liste', 'smart home', 'verfuegbar', 'available']),
    ('trigger_smart_home_scene', 'Activate a scene or automation', 'smart_home', TRUE, FALSE,
     '{"scene_name": "string"}',
     ARRAY['szene', 'scene', 'automation', 'automatisierung', 'aktivieren', 'activate']),
    ('get_smart_home_history', 'Get history of device states', 'smart_home', TRUE, FALSE,
     '{"entity_id": "string", "hours": "optional int"}',
     ARRAY['history', 'verlauf', 'historie', 'changes', 'aenderungen'])
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    parameters = EXCLUDED.parameters,
    keywords = EXCLUDED.keywords;
