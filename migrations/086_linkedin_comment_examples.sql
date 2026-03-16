-- Migration: 086_linkedin_comment_examples
-- Complete ready-to-use comment examples for different scenarios
-- Created: 2026-03-14

-- Ready-to-use comment examples
CREATE TABLE IF NOT EXISTS content_playbook_comment_examples (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    category VARCHAR(100) NOT NULL,  -- project_launch, immersive, mapping, technology, venue, collegial, personal
    comment_text TEXT NOT NULL,
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    is_favorite BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comment_examples_playbook ON content_playbook_comment_examples(playbook_id);
CREATE INDEX IF NOT EXISTS idx_comment_examples_category ON content_playbook_comment_examples(category);

-- Insert complete comment examples
DO $$
DECLARE
    playbook_id INTEGER;
BEGIN
    SELECT id INTO playbook_id FROM content_playbooks WHERE domain = 'linkedin_comment' LIMIT 1;

    -- 1. Projektankuendigungen
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'project_launch', 'Super cool! Drei Monate fuer so eine Installation ist wirklich sportlich. Chapeau! Schoen zu sehen, wenn aus Technik, Raum und Story ein echtes Erlebnis entsteht.'),
    (playbook_id, 'project_launch', 'Sehr schoenes Projekt. Man kann sich gut vorstellen, was da an Abstimmung zwischen Content, Technik und Raum dahinter steckt. Grossen Respekt ans Team!'),
    (playbook_id, 'project_launch', 'Super cool! Genau solche Projekte zeigen, was passiert, wenn Technik und Inszenierung wirklich zusammenspielen.');

    -- 2. Immersive / Experience Projekte
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'immersive', 'Sehr spannend zu sehen. Wenn Technik, Raum und Story zusammenkommen, entsteht genau die Art Erlebnis, die im Publikum haengen bleibt.'),
    (playbook_id, 'immersive', 'Super cool! Immer schoen zu sehen, wenn immersive Projekte nicht nur gut aussehen, sondern sich im Raum auch richtig anfuehlen.'),
    (playbook_id, 'immersive', 'Starkes Projekt. Wenn Systeme, Raum und Dramaturgie zusammenfinden, wird aus Infrastruktur ploetzlich Emotion.');

    -- 3. Projection Mapping / Visual Systems
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'mapping', 'Super cool! Mapping bleibt einfach eine besondere Mischung aus Technik, Timing und ein bisschen Magie.'),
    (playbook_id, 'mapping', 'Sehr schoenes Mapping. Man sieht sofort, wie viel Planung und Feinarbeit dahinter steckt.'),
    (playbook_id, 'mapping', 'Super stark! Wenn Mapping, Raum und Story wirklich zusammenspielen, entsteht genau dieser Moment, in dem das Publikum kurz vergisst, wie es technisch funktioniert.');

    -- 4. Technologie / Systems Posts
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'technology', 'Spannend zu sehen. Die Technik gibt es inzwischen ueberall - die eigentliche Kunst liegt darin, alles sinnvoll zusammen zu orchestrieren.'),
    (playbook_id, 'technology', 'Genau das. Die Systeme sind heute selten das Problem. Die Herausforderung ist, sie so zu verbinden, dass daraus ein echtes Erlebnis entsteht.'),
    (playbook_id, 'technology', 'Sehr guter Punkt. Wenn Systeme wirklich zusammenspielen, merkt das Publikum die Technik ploetzlich gar nicht mehr.');

    -- 5. Event / Stadion / Venue
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'venue', 'Super spannend! Wenn Licht, Content, Spielmoment und Raum zusammenkommen, wird aus einem Stadion ploetzlich eine Buehne.'),
    (playbook_id, 'venue', 'Sehr cooles Setup. Da merkt man sofort, wie viel Dramaturgie in solchen Projekten steckt.'),
    (playbook_id, 'venue', 'Schoen zu sehen, wie Venue-Technologie immer mehr Richtung Erlebnis gedacht wird.');

    -- 6. Kollegiale Unterstuetzung
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'collegial', 'Grossen Respekt ans ganze Team. Solche Projekte entstehen nie alleine.'),
    (playbook_id, 'collegial', 'Stark! Da steckt sicher einiges an Planung und Koordination dahinter.'),
    (playbook_id, 'collegial', 'Super schoen umgesetzt. Freut mich sehr zu sehen!');

    -- 7. Persoenlich (wenn man jemanden kennt)
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text) VALUES
    (playbook_id, 'personal', 'Sehr cool! Freut mich besonders zu sehen, was ihr da gebaut habt.'),
    (playbook_id, 'personal', 'Starkes Projekt. Schoen zu sehen, was bei euch im Studio entsteht.'),
    (playbook_id, 'personal', 'Super cool! Ich weiss ja, wie viel Arbeit hinter solchen Projekten steckt.');

    -- Micha-Signatur-Saetze (Bonus)
    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text, is_favorite) VALUES
    (playbook_id, 'signature', 'Der Markt wird definitiv nicht langweiliger.', true),
    (playbook_id, 'signature', 'Da passiert gerade einiges.', true),
    (playbook_id, 'signature', 'Man sieht sich sicher irgendwo im Feld.', true),
    (playbook_id, 'signature', 'Solche Projekte bleiben haengen.', true),
    (playbook_id, 'signature', 'Da juckts einen ja direkt wieder in den Fingern.', true);

END $$;
