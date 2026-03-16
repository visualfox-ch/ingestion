-- Migration: 084_linkedin_playbook_extended
-- Extended LinkedIn Playbook: Target accounts, Post types, Strategy
-- Created: 2026-03-14

-- Target Accounts (accounts to engage with)
CREATE TABLE IF NOT EXISTS content_playbook_targets (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    group_name VARCHAR(255) NOT NULL,
    group_description TEXT,
    why_important TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Individual accounts within target groups
CREATE TABLE IF NOT EXISTS content_playbook_target_accounts (
    id SERIAL PRIMARY KEY,
    target_group_id INTEGER REFERENCES content_playbook_targets(id) ON DELETE CASCADE,
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(100),  -- company, person, organization
    notes TEXT,
    is_priority BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Post types / formats
CREATE TABLE IF NOT EXISTS content_playbook_post_types (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    type_name VARCHAR(255) NOT NULL,
    type_key VARCHAR(100) NOT NULL,
    description TEXT,
    why_it_works TEXT,
    example_post TEXT,
    is_recommended BOOLEAN DEFAULT true,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Strategy guidelines
CREATE TABLE IF NOT EXISTS content_playbook_strategy (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    category VARCHAR(100) NOT NULL,  -- routine, do, dont, principle
    guideline TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_target_playbook ON content_playbook_targets(playbook_id);
CREATE INDEX IF NOT EXISTS idx_target_accounts_group ON content_playbook_target_accounts(target_group_id);
CREATE INDEX IF NOT EXISTS idx_post_types_playbook ON content_playbook_post_types(playbook_id);
CREATE INDEX IF NOT EXISTS idx_strategy_playbook ON content_playbook_strategy(playbook_id);
CREATE INDEX IF NOT EXISTS idx_strategy_category ON content_playbook_strategy(category);

-- Insert data for LinkedIn Comment Playbook
DO $$
DECLARE
    playbook_id INTEGER;
    group_mediaserver INTEGER;
    group_avrental INTEGER;
    group_immersive INTEGER;
    group_consultants INTEGER;
    group_venue INTEGER;
BEGIN
    SELECT id INTO playbook_id FROM content_playbooks WHERE domain = 'linkedin_comment' LIMIT 1;

    -- Target Group 1: Media Server / AV Hersteller
    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (
        playbook_id,
        'Media Server / AV Hersteller',
        'Firmen die Technologie praegen, Projekte sehen, Operatoren kennen',
        'Media-Server-Leute kennen sich untereinander. Sichtbarkeit hier zahlt sich aus.',
        1
    ) RETURNING id INTO group_mediaserver;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, is_priority) VALUES
    (group_mediaserver, 'AV Stumpfl / PIXERA', 'company', true),
    (group_mediaserver, 'Ross Video', 'company', true),
    (group_mediaserver, 'disguise', 'company', true),
    (group_mediaserver, 'Analog Way', 'company', false),
    (group_mediaserver, 'Modulo Pi', 'company', false),
    (group_mediaserver, 'Dataton WATCHOUT', 'company', false);

    -- Target Group 2: AV Rental / Production Companies
    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (
        playbook_id,
        'AV Rental / Production Companies',
        'Firmen die regelmaessig Operatoren suchen, Projekte vergeben, Freelancer buchen',
        'Wenn du bei deren Projekten kommentierst, sehen Technical Directors, Disposition, Producers deinen Namen.',
        2
    ) RETURNING id INTO group_avrental;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, is_priority) VALUES
    (group_avrental, 'publitec', 'company', true),
    (group_avrental, 'NicLen', 'company', true),
    (group_avrental, 'AED Group', 'company', false),
    (group_avrental, 'PRG', 'company', false),
    (group_avrental, 'Creative Technology', 'company', false),
    (group_avrental, 'Lang Baranday', 'company', false);

    -- Target Group 3: Immersive / Experience Studios
    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (
        playbook_id,
        'Immersive / Experience Studios',
        'Studios die immersive exhibitions, light art installations, projection mapping machen',
        'Langfristig spannendstes Feld. Hier entstehen die innovativen Projekte.',
        3
    ) RETURNING id INTO group_immersive;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, is_priority) VALUES
    (group_immersive, 'Moment Factory', 'company', true),
    (group_immersive, 'Media Apparat', 'company', true),
    (group_immersive, 'Things Happen Studio', 'company', false),
    (group_immersive, 'teamLab', 'company', false),
    (group_immersive, 'Marshmallow Laser Feast', 'company', false);

    -- Target Group 4: Immersive Consultants / Curators
    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (
        playbook_id,
        'Immersive Consultants / Curators',
        'Leute die Projekte kuratieren, Studios empfehlen, Teams bauen',
        'Diese Leute lesen Kommentare sehr bewusst. Einflussreich in der Szene.',
        4
    ) RETURNING id INTO group_consultants;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, is_priority) VALUES
    (group_consultants, 'Dorothy Di Stefano', 'person', true),
    (group_consultants, 'Cecile Andreu', 'person', true),
    (group_consultants, 'WXO (World Experience Organization)', 'organization', false),
    (group_consultants, 'The Immersive Experience Institute', 'organization', false);

    -- Target Group 5: Event / Venue / Stadium Tech
    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (
        playbook_id,
        'Event / Venue / Stadium Tech',
        'Hier entstehen die grossen Budgets - Stadion- und Venue-Technologie',
        'Grosse Projekte, langfristige Engagements, professionelle Strukturen.',
        5
    ) RETURNING id INTO group_venue;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, is_priority) VALUES
    (group_venue, 'SAP Garden', 'company', true),
    (group_venue, 'Sports Venue Tech', 'company', false),
    (group_venue, 'Ross Experiential', 'company', false),
    (group_venue, 'Stadium Technology', 'company', false),
    (group_venue, 'Live Experience Designers', 'company', false);

    -- Post Types
    INSERT INTO content_playbook_post_types (playbook_id, type_name, type_key, description, why_it_works, example_post, sort_order) VALUES
    (playbook_id, 'Production Reality', 'production_reality',
     'Posts ueber die Realitaet hinter Shows - Dinge die in der Planung niemand bedenkt, die erst beim Aufbau passieren.',
     'Erfahrung zeigen, keine Selbstpromotion, Systems-Denken demonstrieren.',
     E'Immersive Shows beginnen oft mit einer Idee.\n\nEine Welt.\nEine Geschichte.\nEine Stimmung.\n\nAber irgendwann kommt der Moment, in dem alles durch echte Systeme laufen muss.\n\nServer.\nSignalwege.\nTiming.\n\nWenn das funktioniert, spricht niemand mehr ueber Technik.\n\nDann bleibt nur das Erlebnis.',
     1),
    (playbook_id, 'Lessons from the Field', 'lessons_field',
     'Mini-Learnings aus Projekten - kurz, ehrlich, praxisnah.',
     'Beliebt weil kurz, ehrlich und direkt anwendbar.',
     E'Drei Dinge, die Touring-Shows ueber Systemdesign lehren:\n1. Alles wird irgendwann kaputtgehen.\n2. Der Raum ist nie so wie im Plan.\n3. Redundanz ist keine Paranoia.',
     2),
    (playbook_id, 'Technology vs Emotion', 'tech_emotion',
     'Die Balance zwischen technischer Exzellenz und emotionaler Wirkung.',
     'Funktioniert extrem gut in der immersive Szene. Zeigt Verstaendnis fuer beide Seiten.',
     E'Technologie im Eventbereich wird immer besser.\n\nMehr LED.\nMehr Server.\nMehr Automation.\n\nAber die eigentliche Frage bleibt immer gleich:\n\nFuehlt das Publikum etwas?',
     3),
    (playbook_id, 'System Thinking', 'system_thinking',
     'Erklaere Dinge die andere nicht sehen - Strukturen und Zusammenhaenge.',
     'Positioniert dich als Systems-Guy der das grosse Bild versteht.',
     E'Wenn immersive Shows scheitern, liegt es selten an der Idee.\n\nMeist liegt es daran, dass die Struktur dahinter fehlt.\n\nIdeen inspirieren.\nSysteme halten sie am Leben.',
     4),
    (playbook_id, 'Appreciation Posts', 'appreciation',
     'Reposte Projekte anderer mit ehrlichem Respekt, kleiner technischer Beobachtung, emotionaler Wirkung.',
     'Erzeugt Gespraeche, Kontakte und Sichtbarkeit. Niedrige Barriere, hoher Impact.',
     NULL,
     5);

    -- Strategy: Routine
    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (playbook_id, 'routine', '1 eigener Post pro Woche', 1),
    (playbook_id, 'routine', '4-6 Kommentare pro Woche', 2),
    (playbook_id, 'routine', '2-3 neue Kontakte pro Woche', 3);

    -- Strategy: What to comment on (DO)
    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (playbook_id, 'do', 'Projekt Launch', 1),
    (playbook_id, 'do', 'Projekt Abschluss', 2),
    (playbook_id, 'do', 'Neue Installation', 3),
    (playbook_id, 'do', 'Immersive Show', 4),
    (playbook_id, 'do', 'Venue / Stadion Projekt', 5);

    -- Strategy: What NOT to comment on (DONT)
    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (playbook_id, 'dont', 'Motivationsposts', 1),
    (playbook_id, 'dont', 'Generische Leadership Posts', 2),
    (playbook_id, 'dont', 'Marketing-Blabla', 3);

    -- Strategy: Key Principles
    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (playbook_id, 'principle', 'Ziel ist nicht Reichweite, sondern Reputation bei den richtigen Entscheidern.', 1),
    (playbook_id, 'principle', 'LinkedIn funktioniert: Kommentare → Profilbesuche → Kontaktanfragen. Nicht: Post → Viral → Projekte.', 2),
    (playbook_id, 'principle', 'Du musst nicht viel posten, sondern die richtigen Dinge.', 3),
    (playbook_id, 'principle', 'Wenn du regelmaessig bei den richtigen Leuten kommentierst, wirst du in deinem Feld schnell sichtbar.', 4);

END $$;
