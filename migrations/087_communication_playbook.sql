-- Migration: 087_communication_playbook
-- Communication Coaching Playbook: SBI, DESC, NVC frameworks with phrase libraries
-- Created: 2026-03-14

-- Insert Communication Playbook
INSERT INTO content_playbooks (domain, name, version, description, purpose, golden_rule)
VALUES (
    'communication',
    'Communication Coaching Playbook',
    '1.0',
    'Frameworks und Phrasen fuer schwierige Gespraeche, Feedback und Konfliktloesung',
    'Strukturierte, empathische Kommunikation in herausfordernden Situationen',
    'Verhalten beschreiben, nicht Person bewerten. Ich-Statements statt Du-Vorwuerfe.'
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
    sec_opening INTEGER;
    sec_acknowledge INTEGER;
    sec_behavior INTEGER;
    sec_impact INTEGER;
    sec_request INTEGER;
    sec_closing INTEGER;
BEGIN
    SELECT id INTO pb_id FROM content_playbooks WHERE domain = 'communication' LIMIT 1;

    -- ============ FORMULAS ============

    INSERT INTO content_playbook_formulas (playbook_id, name, formula, example)
    VALUES
    (pb_id, 'SBI Framework',
     'Situation → Behavior → Impact',
     'In unserem Meeting gestern (Situation) hast du mich zweimal unterbrochen (Behavior). Das hat mich aus dem Konzept gebracht und ich konnte meinen Punkt nicht zu Ende bringen (Impact).'),
    (pb_id, 'DESC Framework',
     'Describe → Express → Specify → Consequences',
     'Wenn Deadlines nicht eingehalten werden (Describe), macht mich das nervoes weil ich meine eigene Planung nicht halten kann (Express). Ich brauche mindestens 2 Tage Vorlauf bei Verspaetungen (Specify). Dann kann ich umplanen und wir vermeiden Stress (Consequences).'),
    (pb_id, 'NVC Framework',
     'Observation → Feeling → Need → Request',
     'Ich habe bemerkt, dass die letzten drei Reports ohne Abstimmung rausgingen (Observation). Ich fuehle mich uebergangen (Feeling), weil mir Teamabstimmung wichtig ist (Need). Koennten wir einen kurzen Check-in vor dem Versand einbauen? (Request)');

    -- ============ SECTIONS + PHRASES ============

    -- Opening phrases
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'opening', 'Gespraechseroeffnung', 'Ruhiger, nicht konfrontativer Einstieg', 'Zu Beginn eines schwierigen Gespraechs', 1)
    RETURNING id INTO sec_opening;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_opening, 'Ich wuerde gerne kurz mit dir ueber etwas sprechen. Hast du gerade 10 Minuten?', 'neutral'),
    (sec_opening, 'Mir ist etwas aufgefallen, das ich gerne mit dir besprechen wuerde.', 'neutral'),
    (sec_opening, 'Ich habe ein Thema, bei dem ich deine Perspektive hoeren moechte.', 'collaborative'),
    (sec_opening, 'Es gibt etwas, das mich beschaeftigt. Koennen wir kurz reden?', 'personal'),
    (sec_opening, 'Ich moechte sicherstellen, dass wir auf dem gleichen Stand sind bei...', 'alignment'),
    (sec_opening, 'Bevor das groesser wird, wuerde ich gerne direkt mit dir sprechen.', 'proactive');

    -- Emotion acknowledgment
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'acknowledge', 'Emotionen anerkennen', 'Validieren ohne zuzustimmen', 'Wenn der andere emotional reagiert', 2)
    RETURNING id INTO sec_acknowledge;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_acknowledge, 'Ich verstehe, dass das frustrierend ist.', 'validation'),
    (sec_acknowledge, 'Das klingt wirklich belastend.', 'empathy'),
    (sec_acknowledge, 'Ich kann nachvollziehen, dass dich das aergert.', 'understanding'),
    (sec_acknowledge, 'Es ist verstaendlich, dass du so reagierst.', 'normalizing'),
    (sec_acknowledge, 'Danke, dass du das so offen sagst.', 'appreciation'),
    (sec_acknowledge, 'Ich hoere, dass dir das wichtig ist.', 'active_listening'),
    (sec_acknowledge, 'Das war sicher nicht einfach fuer dich.', 'empathy'),
    (sec_acknowledge, 'Ich sehe, dass dich das beschaeftigt.', 'observation');

    -- Behavior description (neutral)
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'behavior', 'Verhalten beschreiben', 'Konkret, beobachtbar, ohne Interpretation', 'SBI/DESC Kernpunkt', 3)
    RETURNING id INTO sec_behavior;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_behavior, 'Was ich beobachtet habe ist...', 'observation'),
    (sec_behavior, 'Konkret meine ich folgende Situation...', 'specific'),
    (sec_behavior, 'In den letzten [Zeitraum] ist mir aufgefallen, dass...', 'pattern'),
    (sec_behavior, 'Gestern im Meeting hast du...', 'specific'),
    (sec_behavior, 'Die letzten drei Mal ist folgendes passiert...', 'pattern'),
    (sec_behavior, 'Wenn [konkrete Situation], dann [konkretes Verhalten]...', 'conditional');

    -- Impact statements
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'impact', 'Impact beschreiben', 'Ich-Perspektive, konkrete Auswirkungen', 'Nach Verhaltensbeschreibung', 4)
    RETURNING id INTO sec_impact;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_impact, 'Das fuehrt bei mir dazu, dass...', 'personal'),
    (sec_impact, 'Die Auswirkung davon ist...', 'factual'),
    (sec_impact, 'Fuer das Team bedeutet das...', 'team'),
    (sec_impact, 'Dadurch entsteht folgendes Problem...', 'consequence'),
    (sec_impact, 'Ich fuehle mich dabei...', 'emotional'),
    (sec_impact, 'Das macht es schwierig fuer mich, weil...', 'personal'),
    (sec_impact, 'Die Konsequenz ist, dass wir...', 'business');

    -- Request / Solution
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'request', 'Bitte / Loesungsvorschlag', 'Konkret, machbar, zukunftsorientiert', 'Abschluss des Feedbacks', 5)
    RETURNING id INTO sec_request;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_request, 'Was ich mir wuenschen wuerde ist...', 'wish'),
    (sec_request, 'Koennten wir vereinbaren, dass...', 'agreement'),
    (sec_request, 'Mein Vorschlag waere...', 'solution'),
    (sec_request, 'Was hieltest du davon, wenn wir...', 'collaborative'),
    (sec_request, 'Ich brauche von dir...', 'direct'),
    (sec_request, 'Lass uns gemeinsam ueberlegen, wie wir...', 'collaborative'),
    (sec_request, 'Ein erster Schritt koennte sein...', 'incremental'),
    (sec_request, 'Waere es moeglich, dass du kuenftig...', 'polite');

    -- Closing / Agreement
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'closing', 'Gespraechsabschluss', 'Naechste Schritte, Wertschaetzung', 'Ende des Gespraechs', 6)
    RETURNING id INTO sec_closing;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_closing, 'Danke, dass du dir die Zeit genommen hast.', 'appreciation'),
    (sec_closing, 'Ich schaetze, dass wir das offen besprechen konnten.', 'appreciation'),
    (sec_closing, 'Lass uns in einer Woche nochmal schauen, wie es laeuft.', 'followup'),
    (sec_closing, 'Koennen wir so verbleiben?', 'confirmation'),
    (sec_closing, 'Ich freue mich, dass wir eine Loesung gefunden haben.', 'positive'),
    (sec_closing, 'Falls noch etwas unklar ist, melde dich gerne.', 'open_door'),
    (sec_closing, 'Ich bin froh, dass wir das geklaert haben.', 'relief');

    -- ============ FORBIDDEN PHRASES ============

    INSERT INTO content_playbook_forbidden (playbook_id, phrase, reason) VALUES
    (pb_id, 'Du bist immer...', 'Generalisierung, triggert Abwehr'),
    (pb_id, 'Du machst nie...', 'Generalisierung, triggert Abwehr'),
    (pb_id, 'Das ist doch nicht so schlimm', 'Minimiert Gefuehle des anderen'),
    (pb_id, 'Beruhig dich mal', 'Invalidiert Emotionen'),
    (pb_id, 'Du uebertreibst', 'Invalidiert Perspektive'),
    (pb_id, 'Jeder weiss doch...', 'Passiv-aggressiv'),
    (pb_id, 'Ich will ja nicht kritisieren, aber...', 'Aber-Konstruktion negiert alles davor'),
    (pb_id, 'Nimm es nicht persoenlich', 'Funktioniert nie'),
    (pb_id, 'Das habe ich nicht so gemeint', 'Verantwortung abschieben'),
    (pb_id, 'Wenn du nur...', 'Schuldzuweisung');

    -- ============ TARGETS ============

    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES
    (pb_id, 'Peers / Kollegen', 'Gleichgestellte im Team oder anderen Abteilungen', 'Haeufigste Feedback-Situation, Balance zwischen Direktheit und Beziehungserhalt', 1),
    (pb_id, 'Direct Reports', 'Mitarbeiter die an dich berichten', 'Machtgefaelle beachten, klare Erwartungen setzen', 2),
    (pb_id, 'Manager / Vorgesetzte', 'Dein Chef oder dessen Chef', 'Respektvoll aber klar, gut vorbereitet, Loesungsorientiert', 3),
    (pb_id, 'Kunden / Externe', 'Kunden, Partner, Dienstleister', 'Professionell bleiben, Eskalation vermeiden, schriftlich nachhalten', 4);

    -- ============ STRATEGY ============

    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (pb_id, 'preparation', 'Konkretes Beispiel vorbereiten, nicht aus dem Bauch heraus', 1),
    (pb_id, 'preparation', 'Eigene Emotionen vorher sortieren', 2),
    (pb_id, 'preparation', 'Ziel des Gespraechs klar haben', 3),
    (pb_id, 'timing', 'Nicht zwischen Tuer und Angel', 1),
    (pb_id, 'timing', 'Nicht direkt nach dem Vorfall wenn Emotionen hoch', 2),
    (pb_id, 'timing', 'Aber auch nicht zu lange warten (max 48h)', 3),
    (pb_id, 'do', 'Ich-Statements verwenden', 1),
    (pb_id, 'do', 'Konkretes Verhalten benennen, nicht Charakter', 2),
    (pb_id, 'do', 'Zuhoeren und Perspektive erfragen', 3),
    (pb_id, 'do', 'Gemeinsame Loesung erarbeiten', 4),
    (pb_id, 'dont', 'Im Affekt ansprechen', 1),
    (pb_id, 'dont', 'Vor anderen kritisieren', 2),
    (pb_id, 'dont', 'Alte Geschichten aufwaermen', 3),
    (pb_id, 'dont', 'Ultimaten stellen', 4);

    -- ============ STYLE ELEMENTS ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (pb_id, 'tone', 'Ruhig aber bestimmt',
     'Nicht aggressiv, nicht unterwuerfig. Sachlich mit Waerme.',
     ARRAY['Ich moechte das ansprechen...', 'Mir ist wichtig, dass wir...'], 1),
    (pb_id, 'tone', 'Empathisch aber klar',
     'Verstaendnis zeigen ohne eigene Position aufzugeben.',
     ARRAY['Ich verstehe deine Perspektive, und gleichzeitig...', 'Das ist nachvollziehbar. Was ich brauche ist...'], 2),
    (pb_id, 'structure', 'Sandwich vermeiden',
     'Kein Lob-Kritik-Lob. Lieber direkt und ehrlich.',
     ARRAY['Direkt zum Punkt', 'Klare Trennung: Feedback ist Feedback, Lob ist Lob'], 3),
    (pb_id, 'avoid', 'Passive Aggression',
     'Keine versteckten Vorwuerfe, keine Ironie.',
     ARRAY['Schoen dass du es auch mal schaffst', 'Das haette ich von dir nicht erwartet'], 4);

END $$;
