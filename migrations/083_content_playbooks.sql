-- Migration: 083_content_playbooks
-- Content Playbooks for LinkedIn Coach and other content generation
-- Created: 2026-03-14

-- Main playbook table
CREATE TABLE IF NOT EXISTS content_playbooks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(100) NOT NULL,  -- linkedin, email, presentation, etc.
    version VARCHAR(20) DEFAULT '1.0',
    description TEXT,
    purpose TEXT,
    golden_rule TEXT,  -- The core principle
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Playbook sections (like "Einstiegsbibliothek", "Praxisbeobachtungen")
CREATE TABLE IF NOT EXISTS content_playbook_sections (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    section_key VARCHAR(100) NOT NULL,  -- einstieg, praxis, respekt, etc.
    section_name VARCHAR(255) NOT NULL,
    description TEXT,
    usage_context TEXT,  -- When to use this section
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Phrases/templates within sections
CREATE TABLE IF NOT EXISTS content_playbook_phrases (
    id SERIAL PRIMARY KEY,
    section_id INTEGER REFERENCES content_playbook_sections(id) ON DELETE CASCADE,
    phrase TEXT NOT NULL,
    category VARCHAR(100),  -- mapping, venue, immersive, etc.
    language VARCHAR(10) DEFAULT 'de',
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Structure/formulas for the playbook
CREATE TABLE IF NOT EXISTS content_playbook_formulas (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    formula TEXT NOT NULL,  -- e.g., "Einstieg + Praxis + Respekt"
    description TEXT,
    example TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Anti-patterns / forbidden phrases
CREATE TABLE IF NOT EXISTS content_playbook_forbidden (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    phrase TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Best practices / recommendations
CREATE TABLE IF NOT EXISTS content_playbook_recommendations (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    category VARCHAR(100),  -- timing, targets, routine
    recommendation TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_playbook_domain ON content_playbooks(domain);
CREATE INDEX IF NOT EXISTS idx_playbook_active ON content_playbooks(is_active);
CREATE INDEX IF NOT EXISTS idx_section_playbook ON content_playbook_sections(playbook_id);
CREATE INDEX IF NOT EXISTS idx_phrase_section ON content_playbook_phrases(section_id);
CREATE INDEX IF NOT EXISTS idx_phrase_category ON content_playbook_phrases(category);

-- Insert LinkedIn Comment Playbook
INSERT INTO content_playbooks (name, domain, version, description, purpose, golden_rule)
VALUES (
    'LinkedIn Kommentar Playbook',
    'linkedin_comment',
    '1.0',
    'Micha Style - Authentische Kommentare ohne LinkedIn-Blabla',
    'Schnell authentische Kommentare schreiben, die fachlich wirken, Persoenlichkeit zeigen und Gespraeche ausloesen.',
    'Ein guter Kommentar soll klingen wie: Ein erfahrener Kollege, der kurz seine Beobachtung teilt. Nicht wie Marketing.'
);

-- Get the playbook ID for subsequent inserts
DO $$
DECLARE
    playbook_id INTEGER;
    section_einstieg INTEGER;
    section_praxis INTEGER;
    section_immersive INTEGER;
    section_mapping INTEGER;
    section_venue INTEGER;
    section_respekt INTEGER;
    section_persoenlich INTEGER;
    section_abschluss INTEGER;
BEGIN
    SELECT id INTO playbook_id FROM content_playbooks WHERE domain = 'linkedin_comment' LIMIT 1;

    -- Insert formula
    INSERT INTO content_playbook_formulas (playbook_id, name, formula, description, example)
    VALUES (
        playbook_id,
        'Grundformel',
        'Einstieg + Praxis + Respekt',
        'Ein guter Kommentar enthaelt immer: 1. Menschlicher Einstieg, 2. Beobachtung aus der Praxis, 3. Wertschaetzung / Augenzwinkern',
        'Super cool! Drei Monate fuer so eine Installation ist wirklich sportlich. Grossen Respekt ans ganze Team.'
    );

    -- Section 1: Einstiegsbibliothek
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, sort_order)
    VALUES (playbook_id, 'einstieg', 'Einstiegsbibliothek', 'Diese Saetze funktionieren fast immer als Opener.', 1)
    RETURNING id INTO section_einstieg;

    INSERT INTO content_playbook_phrases (section_id, phrase, language) VALUES
    (section_einstieg, 'Super cool!', 'de'),
    (section_einstieg, 'Sehr schoenes Projekt.', 'de'),
    (section_einstieg, 'Spannend zu sehen.', 'de'),
    (section_einstieg, 'Sehr stark umgesetzt.', 'de'),
    (section_einstieg, 'Chapeau!', 'de'),
    (section_einstieg, 'Das schaut richtig gut aus.', 'de'),
    (section_einstieg, 'Da juckts einen ja direkt wieder in den Fingern.', 'de'),
    (section_einstieg, 'Freut mich sehr, das zu sehen.', 'de'),
    (section_einstieg, 'Sehr spannende Arbeit.', 'de');

    -- Section 2: Praxisbeobachtungen
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (playbook_id, 'praxis', 'Praxisbeobachtungen', 'Diese Saetze zeigen Erfahrung aus der Praxis.', 'Production Reality - zeigt dass man weiss wovon man spricht', 2)
    RETURNING id INTO section_praxis;

    INSERT INTO content_playbook_phrases (section_id, phrase, language) VALUES
    (section_praxis, 'Drei Monate fuer so eine Installation ist wirklich sportlich.', 'de'),
    (section_praxis, 'Man kann sich gut vorstellen, wie viel Abstimmung zwischen Content, Technik und Raum dahinter steckt.', 'de'),
    (section_praxis, 'Wenn Technik, Raum und Story wirklich zusammenspielen, entsteht genau diese Art Erlebnis.', 'de'),
    (section_praxis, 'Die Technik gibt es heute fast ueberall - die eigentliche Herausforderung ist, alles sinnvoll zu orchestrieren.', 'de'),
    (section_praxis, 'Mapping bleibt einfach eine besondere Mischung aus Timing, Technik und ein bisschen Magie.', 'de'),
    (section_praxis, 'Wenn Systeme wirklich zusammenlaufen, merkt das Publikum die Technik ploetzlich gar nicht mehr.', 'de'),
    (section_praxis, 'Die eigentliche Arbeit beginnt meistens erst nach der Idee.', 'de');

    -- Section 3: Immersive/Experience
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, sort_order)
    VALUES (playbook_id, 'immersive', 'Immersive / Experience Kommentare', 'Fuer immersive Installationen und Experience-Projekte', 3)
    RETURNING id INTO section_immersive;

    INSERT INTO content_playbook_phrases (section_id, phrase, category, language) VALUES
    (section_immersive, 'Sehr spannend zu sehen, wie immersive Projekte immer mehr Richtung Erlebnis gedacht werden.', 'immersive', 'de'),
    (section_immersive, 'Wenn Raum, Story und Technik zusammenkommen, entsteht genau der Moment, der im Publikum haengen bleibt.', 'immersive', 'de'),
    (section_immersive, 'Schoen zu sehen, wenn immersive Installationen nicht nur gut aussehen, sondern sich im Raum auch richtig anfuehlen.', 'immersive', 'de');

    -- Section 4: Mapping
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, sort_order)
    VALUES (playbook_id, 'mapping', 'Mapping Kommentare', 'Fuer Projection Mapping Projekte', 4)
    RETURNING id INTO section_mapping;

    INSERT INTO content_playbook_phrases (section_id, phrase, category, language) VALUES
    (section_mapping, 'Super cool! Mapping bleibt einfach eine besondere Mischung aus Technik, Timing und ein bisschen Magie.', 'mapping', 'de'),
    (section_mapping, 'Sehr schoenes Mapping. Man sieht sofort, wie viel Planung dahinter steckt.', 'mapping', 'de'),
    (section_mapping, 'Wenn Mapping, Raum und Story wirklich zusammenspielen, entsteht dieser Moment, in dem das Publikum kurz vergisst, wie es technisch funktioniert.', 'mapping', 'de');

    -- Section 5: Venue/Stadion
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, sort_order)
    VALUES (playbook_id, 'venue', 'Venue / Stadion Kommentare', 'Fuer Venue-Technologie und Stadion-Projekte', 5)
    RETURNING id INTO section_venue;

    INSERT INTO content_playbook_phrases (section_id, phrase, category, language) VALUES
    (section_venue, 'Spannend zu sehen, wie Venue-Technologie immer staerker Richtung Erlebnis gedacht wird.', 'venue', 'de'),
    (section_venue, 'Wenn Licht, Content und Raum zusammenkommen, wird aus einem Stadion ploetzlich eine Buehne.', 'venue', 'de'),
    (section_venue, 'Sehr cooles Setup. Da merkt man sofort, wie viel Dramaturgie hinter solchen Projekten steckt.', 'venue', 'de');

    -- Section 6: Kollegiale Wertschaetzung
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, sort_order)
    VALUES (playbook_id, 'respekt', 'Kollegiale Wertschaetzung', 'Respekt und Anerkennung zeigen', 6)
    RETURNING id INTO section_respekt;

    INSERT INTO content_playbook_phrases (section_id, phrase, language) VALUES
    (section_respekt, 'Grossen Respekt ans ganze Team.', 'de'),
    (section_respekt, 'Solche Projekte entstehen nie alleine.', 'de'),
    (section_respekt, 'Stark umgesetzt - freut mich sehr zu sehen.', 'de'),
    (section_respekt, 'Super Arbeit von allen Beteiligten.', 'de');

    -- Section 7: Persoenlich
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (playbook_id, 'persoenlich', 'Persoenliche Kommentare', 'Wenn du Leute kennst', 'Nur verwenden wenn persoenliche Beziehung besteht', 7)
    RETURNING id INTO section_persoenlich;

    INSERT INTO content_playbook_phrases (section_id, phrase, language) VALUES
    (section_persoenlich, 'Freut mich besonders zu sehen, was ihr da gebaut habt.', 'de'),
    (section_persoenlich, 'Ich weiss ja, wie viel Arbeit hinter solchen Projekten steckt.', 'de'),
    (section_persoenlich, 'Sehr cool zu sehen, was bei euch im Studio entsteht.', 'de');

    -- Section 8: Abschluss
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, sort_order)
    VALUES (playbook_id, 'abschluss', 'Abschlussbibliothek', 'Micha Style Abschluesse', 8)
    RETURNING id INTO section_abschluss;

    INSERT INTO content_playbook_phrases (section_id, phrase, language) VALUES
    (section_abschluss, 'Der Markt wird definitiv nicht langweiliger.', 'de'),
    (section_abschluss, 'Da passiert gerade einiges.', 'de'),
    (section_abschluss, 'Solche Projekte bleiben haengen.', 'de'),
    (section_abschluss, 'Man sieht sich sicher irgendwo im Feld.', 'de'),
    (section_abschluss, 'Da kommt bestimmt noch einiges.', 'de');

    -- Insert forbidden phrases
    INSERT INTO content_playbook_forbidden (playbook_id, phrase, reason) VALUES
    (playbook_id, 'Great post!', 'Wirkt generisch'),
    (playbook_id, 'Thanks for sharing!', 'Wirkt generisch'),
    (playbook_id, 'Amazing innovation!', 'Wirkt generisch'),
    (playbook_id, 'Game changer!', 'Wirkt generisch'),
    (playbook_id, 'Thought leadership!', 'Wirkt generisch');

    -- Insert recommendations
    INSERT INTO content_playbook_recommendations (playbook_id, category, recommendation) VALUES
    (playbook_id, 'targets', 'Projektankuendigungen'),
    (playbook_id, 'targets', 'Projektabschluesse'),
    (playbook_id, 'targets', 'Immersive Installationen'),
    (playbook_id, 'targets', 'Mapping Projekte'),
    (playbook_id, 'targets', 'Venue / Stadion Projekte'),
    (playbook_id, 'targets', 'Media Server / AV Technologie'),
    (playbook_id, 'routine', '1 eigener Post pro Woche'),
    (playbook_id, 'routine', '4-6 Kommentare pro Woche'),
    (playbook_id, 'routine', '2-3 neue Kontakte');

END $$;
