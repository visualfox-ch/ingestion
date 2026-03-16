-- Migration: 089_email_playbook
-- Professional Email Playbook: Templates, formulas, and phrase libraries
-- Created: 2026-03-14

-- Insert Email Playbook
INSERT INTO content_playbooks (domain, name, version, description, purpose, golden_rule)
VALUES (
    'email',
    'Professional Email Playbook',
    '1.0',
    'Strukturen und Phrasen fuer professionelle E-Mails',
    'Klare, actionable Emails die gelesen und beantwortet werden',
    'Eine Email, ein Thema, eine Action. Wenn mehr noetig: separates Meeting.'
) ON CONFLICT (domain) DO UPDATE SET
    name = EXCLUDED.name,
    version = EXCLUDED.version,
    description = EXCLUDED.description,
    purpose = EXCLUDED.purpose,
    golden_rule = EXCLUDED.golden_rule;

-- Get playbook ID and insert data
DO $$
DECLARE
    pb_id INTEGER;
    sec_subject INTEGER;
    sec_opening INTEGER;
    sec_body INTEGER;
    sec_request INTEGER;
    sec_closing INTEGER;
    sec_followup INTEGER;
BEGIN
    SELECT id INTO pb_id FROM content_playbooks WHERE domain = 'email' LIMIT 1;

    -- ============ FORMULAS ============

    INSERT INTO content_playbook_formulas (playbook_id, name, formula, example)
    VALUES
    (pb_id, 'BLUF (Bottom Line Up Front)',
     'Key Message First → Context → Details → Action',
     'Wir muessen das Meeting auf Donnerstag verschieben. (BLUF) Der Kunde hat kurzfristig abgesagt wegen interner Umstrukturierung. (Context) Alle anderen Teilnehmer sind Donnerstag 14:00 verfuegbar. (Details) Bitte bestaetigt eure Teilnahme bis morgen. (Action)'),
    (pb_id, 'Request Email',
     'Context → Request → Deadline → Why it matters',
     'Ich arbeite gerade am Q3 Report. (Context) Koenntest du mir die Sales-Zahlen schicken? (Request) Ich braeuchte sie bis Freitag 12:00. (Deadline) Dann schaffe ich es, den Report vor dem Board Meeting fertig zu haben. (Why)'),
    (pb_id, 'Bad News Email',
     'Acknowledge → Explain → Take Responsibility → Solution → Next Steps',
     'Die Deadline werden wir nicht halten. (Acknowledge) Das Supplier-Problem hat laenger gedauert als erwartet. (Explain) Ich haette frueher eskalieren sollen. (Responsibility) Neuer Termin ist der 15. (Solution) Ich schicke morgen ein Update zum Status. (Next Steps)');

    -- ============ SECTIONS + PHRASES ============

    -- Subject Lines
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'subject', 'Subject Lines', 'Klar, spezifisch, actionable', 'Betreffzeile', 1)
    RETURNING id INTO sec_subject;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Request subjects
    (sec_subject, 'Request: [Topic] by [Date]', 'request'),
    (sec_subject, 'Quick ask: [Topic]', 'request'),
    (sec_subject, 'Input needed: [Topic]', 'request'),
    (sec_subject, 'Approval needed: [Topic]', 'approval'),
    -- Status subjects
    (sec_subject, '[Project] Update - [Date/Status]', 'status'),
    (sec_subject, 'Weekly Update: [Project]', 'status'),
    (sec_subject, 'FYI: [Topic]', 'info'),
    -- Action subjects
    (sec_subject, 'Action Required: [Topic] by [Date]', 'urgent'),
    (sec_subject, 'Decision needed: [Topic]', 'decision'),
    (sec_subject, 'URGENT: [Topic]', 'urgent'),
    -- Meeting subjects
    (sec_subject, 'Meeting Request: [Topic] - [Date]', 'meeting'),
    (sec_subject, 'Reschedule: [Meeting] to [New Date]', 'meeting'),
    (sec_subject, 'Agenda: [Meeting] on [Date]', 'meeting'),
    -- Follow-up subjects
    (sec_subject, 'Following up: [Topic]', 'followup'),
    (sec_subject, 'Re: [Topic] - Next Steps', 'followup');

    -- Opening Lines
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'opening', 'Opening Lines', 'Direkt zum Punkt, keine Floskeln', 'Erster Satz', 2)
    RETURNING id INTO sec_opening;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Direct openings
    (sec_opening, 'Kurze Frage zu [Topic]:', 'direct'),
    (sec_opening, 'Hier das Update zu [Topic]:', 'direct'),
    (sec_opening, 'Ich brauche deine Hilfe bei [Topic].', 'direct'),
    (sec_opening, 'Bezueglich unseres Gespraechs:', 'reference'),
    (sec_opening, 'Wie besprochen:', 'reference'),
    -- Context openings
    (sec_opening, 'Im Rahmen von [Project]:', 'context'),
    (sec_opening, 'Fuer das Meeting am [Date]:', 'context'),
    (sec_opening, 'Nach dem Review gestern:', 'context'),
    -- Softer openings (for sensitive topics)
    (sec_opening, 'Ich wollte kurz nachhaken zu [Topic].', 'soft'),
    (sec_opening, 'Eine Sache ist mir aufgefallen:', 'soft');

    -- Body Structures
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'body', 'Body Phrases', 'Klarheit, Struktur, kein Wall-of-Text', 'Hauptteil', 3)
    RETURNING id INTO sec_body;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Structuring
    (sec_body, 'Zusammenfassung:', 'structure'),
    (sec_body, 'Die wichtigsten Punkte:', 'structure'),
    (sec_body, 'Konkret bedeutet das:', 'structure'),
    (sec_body, 'Hintergrund:', 'context'),
    (sec_body, 'Optionen:', 'decision'),
    -- Explaining
    (sec_body, 'Der Grund ist:', 'explanation'),
    (sec_body, 'Das haengt zusammen mit:', 'connection'),
    (sec_body, 'Um das einzuordnen:', 'context'),
    -- Softening
    (sec_body, 'Falls es hilft:', 'offering'),
    (sec_body, 'Eine Moeglichkeit waere:', 'suggestion'),
    (sec_body, 'Mein Vorschlag:', 'suggestion'),
    -- Escalating
    (sec_body, 'Ohne Entscheidung bis [Date] passiert [Consequence].', 'escalation'),
    (sec_body, 'Das blockiert aktuell [Topic].', 'blocker');

    -- Request / Action
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'request', 'Request Phrases', 'Klar, spezifisch, mit Deadline', 'Action Items', 4)
    RETURNING id INTO sec_request;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_request, 'Koenntest du bitte [Action] bis [Date]?', 'polite'),
    (sec_request, 'Ich brauche [Deliverable] bis [Date].', 'direct'),
    (sec_request, 'Bitte bestaetigen:', 'confirmation'),
    (sec_request, 'Bitte pruefe und gib mir Bescheid.', 'review'),
    (sec_request, 'Lass mich wissen, wenn [Condition].', 'conditional'),
    (sec_request, 'Naechste Schritte von deiner Seite:', 'action_list'),
    (sec_request, 'Ich brauche dein Go bis [Date].', 'approval'),
    (sec_request, 'Bitte waehle Option A oder B.', 'decision'),
    (sec_request, 'Falls ich nichts hoere, gehe ich von [Default] aus.', 'default');

    -- Closing Lines
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'closing', 'Closing Lines', 'Kurz, ohne "Bei Fragen stehe ich gerne zur Verfuegung"', 'Abschluss', 5)
    RETURNING id INTO sec_closing;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_closing, 'Danke!', 'short'),
    (sec_closing, 'Danke fuer deine Hilfe.', 'appreciation'),
    (sec_closing, 'Melde dich, falls unklar.', 'open_door'),
    (sec_closing, 'Bis dann.', 'casual'),
    (sec_closing, 'Freue mich auf dein Feedback.', 'anticipation'),
    (sec_closing, 'Lass uns das diese Woche klaren.', 'commitment'),
    (sec_closing, 'Cheers,', 'informal'),
    (sec_closing, 'Beste Gruesse,', 'formal');

    -- Follow-up Phrases
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'followup', 'Follow-up Phrases', 'Nachhaken ohne nervig zu sein', 'Reminder Emails', 6)
    RETURNING id INTO sec_followup;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_followup, 'Kurz nachhaken:', 'soft'),
    (sec_followup, 'Wollte sicherstellen, dass das nicht untergeht.', 'soft'),
    (sec_followup, 'Hast du schon Gelegenheit gehabt, [Topic] anzuschauen?', 'polite'),
    (sec_followup, 'Friendly reminder: [Topic] ist noch offen.', 'reminder'),
    (sec_followup, 'Das brauche ich heute noch.', 'urgent'),
    (sec_followup, 'Ich gehe davon aus, dass [Default] ok ist, falls ich nichts hoere.', 'assumed_yes'),
    (sec_followup, 'Zweiter Versuch - ist das untergegangen?', 'direct'),
    (sec_followup, 'Falls es bei dir nicht geht, an wen kann ich mich wenden?', 'escalation_soft');

    -- ============ FORBIDDEN PHRASES ============

    INSERT INTO content_playbook_forbidden (playbook_id, phrase, reason) VALUES
    (pb_id, 'Ich hoffe, diese Email findet dich wohlauf', 'Leere Floskel'),
    (pb_id, 'Bei Fragen stehe ich gerne zur Verfuegung', 'Selbstverstaendlich, nicht noetig'),
    (pb_id, 'Mit freundlichen Gruessen', 'Zu formell fuer die meisten Kontexte'),
    (pb_id, 'Wie bereits erwaehnt', 'Passiv-aggressiv'),
    (pb_id, 'Ich bin mir nicht sicher, ob du Zeit hast, aber...', 'Unterwuerfig'),
    (pb_id, 'Sorry fuer die Umstaende', 'Entschuldigung ohne Grund'),
    (pb_id, 'Per the below', 'Corporate speak'),
    (pb_id, 'Going forward', 'Buzzword'),
    (pb_id, 'Let me know your thoughts', 'Zu vage - was genau?'),
    (pb_id, 'Just wanted to check in', 'Sagt nichts aus');

    -- ============ POST TYPES / EMAIL TYPES ============

    INSERT INTO content_playbook_post_types (playbook_id, type_name, type_key, description, why_it_works, example_post, sort_order) VALUES
    (pb_id, 'Request Email', 'request', 'Klar fragen, Deadline setzen, Why erklaeren',
     'Macht es dem Empfaenger einfach zu antworten.',
     E'Subject: Input needed: Q3 Numbers by Friday\n\nHi [Name],\n\nIch brauche die Q3 Sales-Zahlen fuer den Board Report.\n\nDeadline: Freitag 12:00\n\nFormat: Excel mit Breakdown nach Region.\n\nDanke!\n[Name]', 1),
    (pb_id, 'Status Update', 'status', 'BLUF, dann Details, keine Romane',
     'Entscheider lesen nur die ersten 2 Saetze.',
     E'Subject: Project Alpha - On Track\n\n**Status:** On track\n**Blockers:** None\n**This Week:** Feature X shipped\n**Next Week:** Start Feature Y\n\nDetails bei Bedarf im Anhang.', 2),
    (pb_id, 'Bad News Email', 'bad_news', 'Direkt, Verantwortung, Loesung, Next Steps',
     'Schlechte Nachrichten verschwinden nicht durch Verzögern.',
     E'Subject: Deadline-Aenderung: Project Beta\n\nWir werden die Deadline nicht halten.\n\nGrund: Unerwartete API-Aenderung vom Partner.\nNeuer Termin: 20. Maerz (+1 Woche)\nMitigation: Parallelisierung von Testing.\n\nIch halte euch auf dem Laufenden.', 3),
    (pb_id, 'Decision Request', 'decision', 'Optionen, Empfehlung, Deadline',
     'Entscheider wollen Optionen, nicht Probleme.',
     E'Subject: Decision needed: Vendor Selection by Wed\n\nWir muessen uns fuer einen Vendor entscheiden.\n\n**Option A:** Acme - Guenstiger, weniger Features\n**Option B:** BetaCorp - Teurer, besserer Support\n\n**Meine Empfehlung:** Option B\n\nBitte Entscheidung bis Mittwoch.', 4),
    (pb_id, 'Introduction Email', 'intro', 'Wer, Warum verbinden, Clear Ask',
     'Double opt-in, beide Seiten wissen warum.',
     E'Subject: Intro: [Person A] <> [Person B]\n\n[Person A], meet [Person B].\n\n[Person A] arbeitet an X, [Person B] hat Expertise in Y.\n\nIch dachte, ihr solltet euch kennenlernen wegen [Reason].\n\nMoving myself to BCC - ueberlasse euch das.', 5);

    -- ============ TARGETS ============

    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES
    (pb_id, 'Manager / Vorgesetzte', 'Dein Chef, Skip-Level, C-Level', 'Kurz, BLUF, respektvoll aber selbstbewusst', 1),
    (pb_id, 'Peers / Kollegen', 'Gleichgestellte intern oder extern', 'Direkt, kollegial, klare Erwartungen', 2),
    (pb_id, 'Direct Reports', 'Deine Mitarbeiter', 'Klar, supportive, Verantwortung delegieren', 3),
    (pb_id, 'Externe / Kunden', 'Kunden, Partner, Vendors', 'Professionell, schriftlich festhalten, Missverstaendnisse vermeiden', 4),
    (pb_id, 'Unbekannte / Cold Email', 'Erstkontakt, Networking', 'Kurz, Value Proposition klar, easy to ignore = easy to respond', 5);

    -- ============ STRATEGY ============

    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (pb_id, 'timing', 'Nicht Freitag Nachmittag senden', 1),
    (pb_id, 'timing', 'Wichtiges am Morgen, nicht End of Day', 2),
    (pb_id, 'timing', 'Follow-up nach 48h ohne Antwort', 3),
    (pb_id, 'structure', 'Max 5 Saetze im Body', 1),
    (pb_id, 'structure', 'Bullet Points > Fliesstext', 2),
    (pb_id, 'structure', 'Eine Action pro Email', 3),
    (pb_id, 'structure', 'Deadline immer explizit', 4),
    (pb_id, 'do', 'Subject Line informativ machen', 1),
    (pb_id, 'do', 'BLUF - wichtigstes zuerst', 2),
    (pb_id, 'do', 'Mobile-friendly formatieren', 3),
    (pb_id, 'do', 'Reply-All nur wenn noetig', 4),
    (pb_id, 'dont', 'Passive Aggression', 1),
    (pb_id, 'dont', 'Wall of Text', 2),
    (pb_id, 'dont', 'CC als Druckmittel', 3),
    (pb_id, 'dont', 'URGENT missbrauchen', 4);

    -- ============ STYLE ELEMENTS ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (pb_id, 'tone', 'Professional Casual',
     'Nicht steif, aber professionell. Wie man mit geschaetzten Kollegen spricht.',
     ARRAY['Hi Max,', 'Danke!', 'Cheers,'], 1),
    (pb_id, 'length', 'Mobile-First',
     'Die meisten lesen auf dem Handy. Max 5 Saetze ohne Scrollen.',
     ARRAY['BLUF im ersten Satz', 'Bullet Points', 'TL;DR fuer laengere Mails'], 2),
    (pb_id, 'clarity', 'Scannable',
     'Fett fuer Keywords, Bullets fuer Listen, White Space.',
     ARRAY['**Deadline:** Freitag', '**Action:** Bitte pruefen', '**Status:** On Track'], 3),
    (pb_id, 'respect', 'Inbox Empathy',
     'Jeder hat zu viele Emails. Respektiere das.',
     ARRAY['Kurz halten', 'Klare Subject Line', 'Nur relevante Leute CC'], 4);

END $$;
