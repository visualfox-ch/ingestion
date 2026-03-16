-- Migration: 085_linkedin_micha_style
-- Micha-Style elements: Post structure, USPs, Comment formula
-- Created: 2026-03-14

-- Micha-specific style elements
CREATE TABLE IF NOT EXISTS content_playbook_style_elements (
    id SERIAL PRIMARY KEY,
    playbook_id INTEGER REFERENCES content_playbooks(id) ON DELETE CASCADE,
    element_type VARCHAR(100) NOT NULL,  -- comment_element, post_structure, usp, avoid
    element_name VARCHAR(255) NOT NULL,
    description TEXT,
    examples TEXT[],
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_style_elements_playbook ON content_playbook_style_elements(playbook_id);
CREATE INDEX IF NOT EXISTS idx_style_elements_type ON content_playbook_style_elements(element_type);

-- Insert Micha-Style data
DO $$
DECLARE
    playbook_id INTEGER;
BEGIN
    SELECT id INTO playbook_id FROM content_playbooks WHERE domain = 'linkedin_comment' LIMIT 1;

    -- Four elements of Micha-Style comments
    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (playbook_id, 'comment_element', 'Lockerer Einstieg',
     'Nicht LinkedIn-Floskel, sondern menschlich. Zeigt sofort Persoenlichkeit.',
     ARRAY['Super cool!', 'Sehr schoenes Projekt.', 'Da juckts einen ja direkt in den Fingern.', 'Das schaut man sich als Mapping-Nerd natuerlich genauer an.', 'Spannend zu sehen.', 'Chapeau!'],
     1),
    (playbook_id, 'comment_element', 'Echte Anerkennung',
     'Immer zeigen, dass du die Arbeit siehst. Respekt fuers Projekt.',
     ARRAY['Grossen Respekt ans ganze Team.', 'Da steckt sicher einiges an Abstimmung dahinter.', 'Solche Projekte bleiben haengen.', 'Sehr stark umgesetzt.', 'Super Arbeit von allen Beteiligten.'],
     2),
    (playbook_id, 'comment_element', 'Perspektive aus der Praxis',
     'Dein groesster USP: Production Reality. Zeige dass du weisst wovon du sprichst.',
     ARRAY['Drei Monate fuer so eine Installation ist sportlich.', 'Wenn Technik, Raum und Story zusammenkommen, entsteht ein echtes Erlebnis.', 'Die eigentliche Herausforderung beginnt, wenn alle Systeme zusammenspielen.', 'Die Technik gibt es ueberall - die Herausforderung ist, alles sinnvoll zu orchestrieren.'],
     3),
    (playbook_id, 'comment_element', 'Lockerer Abschluss',
     'Augenzwinkern, keine harte CTA. Zeigt dass du Teil der Community bist.',
     ARRAY['Der Markt wird definitiv nicht langweiliger.', 'Da passiert gerade einiges.', 'Mal schauen, wo Mapping als naechstes auftaucht.', 'Man sieht sich sicher irgendwo im Feld.', 'Da kommt bestimmt noch einiges.'],
     4);

    -- Post structure (Hook → Praxisbeobachtung → Erkenntnis)
    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (playbook_id, 'post_structure', 'Hook → Praxis → Erkenntnis',
     'Der typische Micha-Post Aufbau: Spannender Einstieg, dann Beobachtung aus der Praxis, dann kleine Erkenntnis.',
     ARRAY['Super spannend zu sehen, wie sich immersive Shows entwickeln.

Frueher ging es darum, was technisch moeglich ist.

Heute geht es darum, wie Systeme zusammenarbeiten.'],
     1);

    -- USPs (Unique Selling Points)
    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (playbook_id, 'usp', 'Techniker',
     'Du bist Techniker - nicht Theoretiker. Du weisst wie Dinge funktionieren.',
     ARRAY['Server', 'Signalwege', 'Timing', 'Systemdesign'],
     1),
    (playbook_id, 'usp', 'Systemdenker',
     'Du siehst das grosse Bild. Wie Teile zusammenarbeiten.',
     ARRAY['Systeme', 'Integration', 'Orchestrierung', 'Redundanz'],
     2),
    (playbook_id, 'usp', 'Production Reality',
     'Du redest ueber Umsetzung, nicht ueber Ideen. Das ist selten.',
     ARRAY['Aufbau', 'Touring', 'Live-Betrieb', 'Troubleshooting'],
     3);

    -- Things to avoid
    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (playbook_id, 'avoid', 'Motivationsposts',
     'Nicht dein Stil. Zu generisch, passt nicht zu Production Reality.',
     ARRAY['Rise and grind', 'Monday motivation', 'Believe in yourself'],
     1),
    (playbook_id, 'avoid', 'Leadership Lessons',
     'Nicht dein Feld. Bleib bei Technik und Systemen.',
     ARRAY['5 things great leaders do', 'How to manage teams'],
     2),
    (playbook_id, 'avoid', 'Buzzword Innovation',
     'Zu abstrakt. Du redest ueber konkrete Dinge.',
     ARRAY['Disruption', 'Paradigm shift', 'Next-gen solutions'],
     3),
    (playbook_id, 'avoid', 'Selbstpromotion',
     'Zeig Arbeit, nicht dich selbst. Projekte sprechen fuer sich.',
     ARRAY['I am proud to announce', 'Thrilled to share'],
     4),
    (playbook_id, 'avoid', 'Jobangebote',
     'Passt nicht zum Content-Creator Profil.',
     ARRAY['We are hiring', 'Join our team'],
     5);

    -- Comment formula (3 Saetze)
    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (playbook_id, 'comment_formula', '3-Satz-Formel',
     'Einfache Struktur: 1. Lockerer Einstieg, 2. Beobachtung aus der Praxis, 3. Respekt / Augenzwinkern',
     ARRAY['Super cool! Drei Monate fuer so eine Installation ist wirklich sportlich. Grossen Respekt ans ganze Team.', 'Sehr schoenes Projekt. Wenn Technik, Raum und Story zusammenkommen, entsteht genau so ein Moment. Der Markt wird definitiv nicht langweiliger.'],
     1);

    -- Key insight
    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (playbook_id, 'insight', 'Kleine LinkedIn Wahrheit',
     'Die besten Leute auf LinkedIn posten nicht viel. Sie kommentieren gut, posten selten, schreiben ehrlich. Das bist genau du.',
     ARRAY['Kommentare > Virale Posts', 'Qualitaet > Quantitaet', 'Ehrlichkeit > Perfektion'],
     1);

END $$;
