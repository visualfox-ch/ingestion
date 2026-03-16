-- Migration: 091_linkedin_micha_learnings
-- Real learnings from Micha's actual LinkedIn posts (2026-03-14 chat analysis)
-- Created: 2026-03-14

DO $$
DECLARE
    pb_id INTEGER;
BEGIN
    SELECT id INTO pb_id FROM content_playbooks WHERE domain = 'linkedin_comment' LIMIT 1;

    -- ============ MICHA'S CONTENT DNA (from real posts) ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES

    -- Brand Positioning
    (pb_id, 'brand_position', 'Erfahrener Praktiker',
     'Nicht cutting-edge Innovator, sondern 15+ Jahre hands-on Erfahrung. Production Reality > Buzzwords.',
     ARRAY['15 Jahre Pandoras Box', 'Trial & Error gehoert dazu', 'Workarounds sind Teil des Jobs'], 100),

    (pb_id, 'brand_position', 'Team-Player nicht Solo-Hero',
     'Wuerdigt immer das Team und Kollegen. Zeigt Respekt fuer andere. Nie Selbstpromotion.',
     ARRAY['Danke an Kim, Markus, Alex...', 'Massive respect to Ivan and the team', 'Schoen wieder mit der Crew zu arbeiten'], 101),

    (pb_id, 'brand_position', 'People over Technology',
     'Posts drehen sich um Menschen, nicht um Technik. Tech ist Mittel zum Zweck.',
     ARRAY['Wenn die Crew Spass hat, wars ein guter Event', 'Sie ist auch hinter der Buehne unkompliziert', 'Macht einfach Spass mit so Leuten'], 102),

    -- Content Patterns
    (pb_id, 'content_pattern', 'Nostalgic Storytelling',
     'Verbindet Vergangenheit mit Gegenwart. Zeigt Evolution und Erfahrung.',
     ARRAY['Als Rechner noch mehr Luefterlarm als Pixel produziert haben', 'Das ist jetzt 15 Jahre her', 'Was fuer eine Reise'], 103),

    (pb_id, 'content_pattern', 'Behind-the-Scenes Honesty',
     'Zeigt die Realitaet hinter den Shows. Ehrlich ueber Challenges.',
     ARRAY['Obwohl ich eigentlich nur auf Screens gestarrt hab', 'Trial & Error', 'Viele Workarounds'], 104),

    (pb_id, 'content_pattern', 'Foto + Text Combo',
     'Foto zeigt Team/Crew/Spass, Text erklaert den Kontext. Beweist was gesagt wird.',
     ARRAY['Man siehts am Foto', 'Happy Crew = guter Event'], 105),

    (pb_id, 'content_pattern', 'Value-Based Endings',
     'Schliesst mit Werten/Erkenntnissen ab, nicht mit CTA.',
     ARRAY['Dann weisst du, es war nicht nur gut, sondern richtig gut', 'Improvisation ist Faehigkeit, Struktur ist Entscheidung', 'Die besten Shows hatten beides'], 106),

    -- Repost Style
    (pb_id, 'repost_style', 'Proud Colleague',
     'Bei Reposts von Bekannten: Zeige dass du sie kennst und respektierst.',
     ARRAY['Always inspiring to see what you create', 'Massive respect to Ivan and the team'], 107),

    (pb_id, 'repost_style', 'Industry Observer',
     'Bei Reposts von Unbekannten: Zeige deine Perspektive und Erfahrung.',
     ARRAY['Dieser Post trifft einen Nerv', 'Ich war auf Produktionen die exakt so begonnen haben'], 108),

    (pb_id, 'repost_style', 'Balanced Take',
     'Nicht nur zustimmen, sondern eigene Perspektive hinzufuegen.',
     ARRAY['Ja und was dabei oft vergessen wird...', 'Make-it-work UND Struktur', 'Improvisation + Planung'], 109);

    -- ============ MICHA'S USPs ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (pb_id, 'usp', '15+ Jahre Media Server Heritage',
     'Pandoras Box seit Anfang dabei. Deep Tech History.',
     ARRAY['Meine ersten Shows als Rechner noch Luefterlarm machten', 'Von Warping als Kunstform zu Realtime-Systemen'], 110),

    (pb_id, 'usp', 'Production Reality',
     'Redet ueber echte Herausforderungen, nicht Marketing.',
     ARRAY['Workarounds gehoeren dazu', 'Was es wirklich kostet: Zeit, Energie, Nerven', 'Improvisation ist Teil des Jobs'], 111),

    (pb_id, 'usp', 'Systems Thinking + Team Spirit',
     'Versteht wie Systeme zusammenspielen UND wie Teams funktionieren.',
     ARRAY['Wenn die Crew Spass hat', 'Respekt gegenueber der Crew', 'Struktur ist Respekt'], 112);

    -- ============ REAL POST EXAMPLES ============

    INSERT INTO content_playbook_comment_examples (playbook_id, category, comment_text, is_favorite) VALUES

    -- Repost Examples (from real posts)
    (pb_id, 'repost_tech_nostalgia',
     'Pandoras Box und der Widget Designer begleiten mich inzwischen seit fast 15 Jahren. Meine ersten Shows damit habe ich gebaut, als Rechner noch fast mehr Luefterlarm als Pixel produziert haben. Schoen zu sehen, dass sich wieder einiges bewegt.', true),

    (pb_id, 'repost_proud_colleague',
     'This is simple and brilliant at the same time! Ive always loved projects where rhythm directly drives the visuals. When sound, visuals and timing lock together in real time, something changes in the room immediately. Massive respect to [Name] and the team.', true),

    (pb_id, 'repost_industry_solidarity',
     'Dieser Post trifft einen Nerv. Und sicher nicht nur meinen! Die Make-it-work-Mentalitaet steckt in jeder Crew. Aber was dabei oft vergessen wird: Was es kostet. Die Crew ist der Backbone jeder Veranstaltung. Improvisation ist eine Faehigkeit. Struktur ist eine Entscheidung.', true),

    -- Post Examples (from real posts)
    (pb_id, 'post_event_recap',
     'Man siehts am Foto: Wenn die Technik laeuft und die Crew Spass hat, wars ein guter Event. [Context]. Danke an [Names] fuer das Vertrauen und die Zusammenarbeit. Und das Beste am Schluss: Wenn sich Kunde und Speaker bei der Technik-Crew bedanken kommen.', true),

    -- Signature Phrases (new)
    (pb_id, 'signature',
     'Das gehoert auch ein bisschen dazu, oder?', true),
    (pb_id, 'signature',
     'Macht einfach Spass mit so Leuten zu arbeiten!', true),
    (pb_id, 'signature',
     'Dann weisst du, es war nicht nur ein guter Event, sondern ein richtig guter.', true),
    (pb_id, 'signature',
     'Ich bin gespannt, welche neuen Moeglichkeiten (und Workarounds) auf uns warten.', true);

    -- ============ KEY NETWORK TARGETS ============

    -- Add Things Happen Studio to targets
    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, notes, is_priority)
    SELECT tg.id, 'Things Happen Studio', 'company', 'Ivan Val - CEO. Haben Projektil-Installation programmiert. Gute Beziehung.', true
    FROM content_playbook_targets tg
    WHERE tg.playbook_id = pb_id AND tg.group_name = 'Immersive / Experience Studios'
    ON CONFLICT DO NOTHING;

    -- Add Christoph Mayer as potential contact
    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, notes, is_priority)
    SELECT tg.id, 'Christoph Mayer', 'person', 'AV Technical Consultant. Gleiche Perspektive auf Dokumentation/Planung. Networking-Potential.', false
    FROM content_playbook_targets tg
    WHERE tg.playbook_id = pb_id AND tg.group_name = 'Immersive Consultants / Curators'
    ON CONFLICT DO NOTHING;

    -- ============ AVOID (from real feedback) ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (pb_id, 'avoid', 'Cutting-Edge Positionierung',
     'Du bist Praktiker, nicht Innovator. Bleib bei Production Reality.',
     ARRAY['Nicht: Next-Gen Solutions', 'Nicht: Disrupting the industry', 'Nicht: Bleeding edge tech'], 120),

    (pb_id, 'avoid', 'Solo-Hero Narrative',
     'Immer Team wuerdigen. Nie nur ich.',
     ARRAY['Nicht: Ich habe gebaut', 'Sondern: Wir haben zusammen', 'Team-Namen nennen'], 121);

END $$;
