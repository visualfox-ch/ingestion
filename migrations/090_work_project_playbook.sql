-- Migration: 090_work_project_playbook
-- Work & Project Coaching Playbook: Status updates, blocker handling, stakeholder communication
-- Created: 2026-03-14

-- Insert Work/Project Playbook
INSERT INTO content_playbooks (domain, name, version, description, purpose, golden_rule)
VALUES (
    'work_project',
    'Work & Project Playbook',
    '1.0',
    'Strukturen und Phrasen fuer Projekt-Updates, Blocker-Handling und Stakeholder-Kommunikation',
    'Klare Status-Kommunikation, proaktives Blocker-Management, effektive Stakeholder-Updates',
    'Probleme frueh kommunizieren. Keine Ueberraschungen fuer Stakeholder.'
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
    sec_status INTEGER;
    sec_blockers INTEGER;
    sec_risk INTEGER;
    sec_stakeholder INTEGER;
    sec_escalation INTEGER;
    sec_wins INTEGER;
BEGIN
    SELECT id INTO pb_id FROM content_playbooks WHERE domain = 'work_project' LIMIT 1;

    -- ============ FORMULAS ============

    INSERT INTO content_playbook_formulas (playbook_id, name, formula, example)
    VALUES
    (pb_id, 'Status Update Formula',
     'Status (RAG) → Progress → Blockers → Next Steps → Ask',
     'Status: GELB. Progress: Feature A shipped, Feature B 80%. Blocker: Warten auf API-Docs vom Partner. Next Steps: Testing starten sobald Docs da. Ask: Kann jemand beim Partner nachhaken?'),
    (pb_id, 'Blocker Analysis',
     'Symptom → Root Cause → Impact → Options → Recommendation',
     'Symptom: Build bricht ab. Root Cause: Dependency Konflikt nach Update. Impact: Kein Deploy moeglich seit 2 Tagen. Options: Rollback oder Fix forward. Recommendation: Rollback, dann sauberes Update planen.'),
    (pb_id, 'Risk Communication',
     'Risk → Probability → Impact → Mitigation → Owner',
     'Risk: Partner-API koennte sich aendern. Probability: Mittel (30%). Impact: 2 Wochen Verzoegerung. Mitigation: Abstraction Layer bauen. Owner: Tech Lead.'),
    (pb_id, 'Stakeholder Update',
     'BLUF → Context → Details (optional) → What You Need',
     'Wir sind on track fuer den Launch. (BLUF) Das Team hat diese Woche die Core Features abgeschlossen. (Context) Testing laeuft, bisher keine Blocker. (Details) Ich brauche finale Freigabe fuer Marketing Assets. (Ask)');

    -- ============ SECTIONS + PHRASES ============

    -- Status Descriptions
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'status', 'Status Beschreibungen', 'RAG Status klar kommunizieren', 'Projekt-Updates', 1)
    RETURNING id INTO sec_status;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Green
    (sec_status, 'On Track - alles laeuft nach Plan.', 'green'),
    (sec_status, 'Wir liegen gut im Zeitplan.', 'green'),
    (sec_status, 'Keine Blocker, Team performt.', 'green'),
    (sec_status, 'Ahead of schedule - Buffer aufgebaut.', 'green'),
    -- Yellow
    (sec_status, 'At Risk - potenzielle Verzoegerung.', 'yellow'),
    (sec_status, 'Wir beobachten [Issue], noch manageable.', 'yellow'),
    (sec_status, 'Leichte Verzoegerung, Mitigation aktiv.', 'yellow'),
    (sec_status, 'Dependencies unklar, klaeren wir diese Woche.', 'yellow'),
    -- Red
    (sec_status, 'Blocked - brauchen Hilfe.', 'red'),
    (sec_status, 'Deadline nicht haltbar ohne Intervention.', 'red'),
    (sec_status, 'Kritischer Blocker seit [Tagen].', 'red'),
    (sec_status, 'Scope oder Timeline muss angepasst werden.', 'red');

    -- Blocker Communication
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'blockers', 'Blocker Kommunikation', 'Blocker klar beschreiben ohne Blame', 'Wenn etwas nicht weitergeht', 2)
    RETURNING id INTO sec_blockers;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Describing blockers
    (sec_blockers, 'Wir stehen aktuell bei [X].', 'neutral'),
    (sec_blockers, 'Warten auf [Deliverable] von [Team/Person].', 'dependency'),
    (sec_blockers, 'Technisches Problem: [Beschreibung].', 'technical'),
    (sec_blockers, 'Entscheidung ausstehend: [Topic].', 'decision'),
    (sec_blockers, 'Ressourcen-Engpass bei [Skill/Team].', 'resource'),
    -- Quantifying impact
    (sec_blockers, 'Das blockiert [X] seit [Y Tagen].', 'impact'),
    (sec_blockers, 'Ohne Loesung verschieben wir uns um [Zeitraum].', 'impact'),
    (sec_blockers, 'Das betrifft [Anzahl] andere Workstreams.', 'impact'),
    -- Requesting help
    (sec_blockers, 'Ich brauche Unterstuetzung bei [Topic].', 'ask'),
    (sec_blockers, 'Kann jemand [Action]?', 'ask'),
    (sec_blockers, 'Wer ist der richtige Ansprechpartner fuer [Topic]?', 'ask');

    -- Risk Communication
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'risk', 'Risiko Kommunikation', 'Risiken frueh und klar kommunizieren', 'Risk Management', 3)
    RETURNING id INTO sec_risk;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Identifying risks
    (sec_risk, 'Ich sehe ein Risiko bei [Topic].', 'identification'),
    (sec_risk, 'Falls [Bedingung], dann [Konsequenz].', 'conditional'),
    (sec_risk, 'Das koennte zum Problem werden, wenn [Trigger].', 'warning'),
    -- Quantifying
    (sec_risk, 'Wahrscheinlichkeit: [hoch/mittel/niedrig].', 'probability'),
    (sec_risk, 'Impact bei Eintreten: [Beschreibung].', 'impact'),
    (sec_risk, 'Worst Case: [Szenario].', 'worst_case'),
    -- Mitigation
    (sec_risk, 'Mitigation: [Plan].', 'mitigation'),
    (sec_risk, 'Fallback waere [Alternative].', 'fallback'),
    (sec_risk, 'Wir koennen das reduzieren durch [Massnahme].', 'reduction');

    -- Stakeholder Updates
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'stakeholder', 'Stakeholder Updates', 'Executive-tauglich, BLUF, kurz', 'Reports an Management', 4)
    RETURNING id INTO sec_stakeholder;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Opening
    (sec_stakeholder, 'Kurzes Update zu [Project]:', 'opening'),
    (sec_stakeholder, 'Stand der Dinge:', 'opening'),
    (sec_stakeholder, 'Zusammenfassung dieser Woche:', 'opening'),
    -- Progress
    (sec_stakeholder, 'Abgeschlossen: [Milestone].', 'progress'),
    (sec_stakeholder, 'Diese Woche shipped: [Features].', 'progress'),
    (sec_stakeholder, 'Fortschritt: [X]% complete.', 'progress'),
    -- Outlook
    (sec_stakeholder, 'Naechste Woche: [Plan].', 'outlook'),
    (sec_stakeholder, 'Naechster Milestone: [Date].', 'outlook'),
    (sec_stakeholder, 'Erwarteter Abschluss: [Date].', 'outlook'),
    -- Ask
    (sec_stakeholder, 'Brauche Entscheidung zu: [Topic].', 'ask'),
    (sec_stakeholder, 'Bitte zur Kenntnis: [Info].', 'fyi'),
    (sec_stakeholder, 'Keine Action noetig, nur FYI.', 'fyi');

    -- Escalation Phrases
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'escalation', 'Eskalation', 'Professionell eskalieren ohne Blame', 'Wenn normale Wege nicht funktionieren', 5)
    RETURNING id INTO sec_escalation;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_escalation, 'Ich eskaliere das, weil [Grund].', 'reason'),
    (sec_escalation, 'Das ist laenger offen als akzeptabel.', 'urgency'),
    (sec_escalation, 'Ich habe [X] versucht, ohne Erfolg.', 'context'),
    (sec_escalation, 'Ohne Eskalation schaffen wir [Deadline] nicht.', 'impact'),
    (sec_escalation, 'Ich brauche deine Hilfe, das zu loesen.', 'ask'),
    (sec_escalation, 'Kannst du [Person/Team] kontaktieren?', 'ask'),
    (sec_escalation, 'Das braucht Management-Attention.', 'level'),
    (sec_escalation, 'Ich wollte dich informieren bevor es groesser wird.', 'proactive');

    -- Wins / Good News
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'wins', 'Erfolge kommunizieren', 'Wins sichtbar machen ohne anzugeben', 'Team Anerkennung, Visibility', 6)
    RETURNING id INTO sec_wins;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_wins, 'Gute Nachrichten:', 'opening'),
    (sec_wins, 'Das Team hat [Achievement] geschafft.', 'team'),
    (sec_wins, 'Milestone erreicht: [Beschreibung].', 'milestone'),
    (sec_wins, 'Besonderer Shoutout an [Person] fuer [Beitrag].', 'recognition'),
    (sec_wins, 'Das war nicht selbstverstaendlich - [Context].', 'context'),
    (sec_wins, 'Ergebnis: [quantifizierter Erfolg].', 'result'),
    (sec_wins, 'Das bringt uns [Benefit].', 'impact'),
    (sec_wins, 'Danke an alle Beteiligten.', 'appreciation');

    -- ============ FORBIDDEN PHRASES ============

    INSERT INTO content_playbook_forbidden (playbook_id, phrase, reason) VALUES
    (pb_id, 'Das ist nicht mein Job', 'Unprofessionell, blockiert'),
    (pb_id, 'Das hat [Person] verbockt', 'Blame, nicht loesungsorientiert'),
    (pb_id, 'Ich habe keine Zeit dafuer', 'Priorisierung kommunizieren, nicht abwehren'),
    (pb_id, 'Das habe ich schon immer gesagt', 'I-told-you-so hilft niemandem'),
    (pb_id, 'Eigentlich muesste [jemand anders]', 'Passiv-aggressiv'),
    (pb_id, 'Das ist nicht moeglich', 'Besser: Das geht unter [Bedingungen]'),
    (pb_id, 'Wir haben das noch nie so gemacht', 'Blockiert Innovation'),
    (pb_id, 'Keine Ahnung', 'Besser: Ich finde es raus'),
    (pb_id, 'Alles bestens', 'Wenn es nicht stimmt - Probleme frueher melden'),
    (pb_id, 'Das ist kompliziert', 'Erklaeren oder vereinfachen');

    -- ============ POST TYPES / UPDATE FORMATS ============

    INSERT INTO content_playbook_post_types (playbook_id, type_name, type_key, description, why_it_works, example_post, sort_order) VALUES
    (pb_id, 'Weekly Status Update', 'weekly', 'Strukturiertes woechtentliches Update',
     'Routine schafft Vertrauen. Stakeholder wissen was sie erwartet.',
     E'**[Project] Weekly Update - KW12**\n\n**Status:** GRUEN\n\n**Abgeschlossen:**\n- Feature A shipped\n- Testing abgeschlossen\n\n**In Progress:**\n- Feature B (80%)\n- Documentation\n\n**Blockers:** Keine\n\n**Naechste Woche:**\n- Feature B abschliessen\n- Staging Deploy\n\n**Ask:** Keine', 1),
    (pb_id, 'Blocker Alert', 'blocker', 'Schnelle Kommunikation bei Blockern',
     'Frueher kommunizieren = mehr Zeit zum Loesen.',
     E'**Blocker Alert: [Project]**\n\n**Was:** API-Endpoint nicht erreichbar\n**Seit:** Gestern 14:00\n**Impact:** Kein Testing moeglich\n**Versucht:** Support kontaktiert, Ticket #1234\n**Brauche:** Eskalation an Partner-Tech-Lead', 2),
    (pb_id, 'Executive Summary', 'executive', 'High-Level fuer C-Level',
     'Executives lesen max 3 Saetze.',
     E'**[Project] Executive Summary**\n\n**TL;DR:** On Track fuer Q2 Launch.\n\n**Key Metric:** 47/50 Features complete (94%).\n\n**Attention Needed:** Budget-Freigabe fuer Cloud-Kosten.\n\n**Next Milestone:** Beta Launch am 15.', 3),
    (pb_id, 'Postmortem Summary', 'postmortem', 'Nach Incidents/Problemen',
     'Lernen ohne Blame. Systeme verbessern.',
     E'**Postmortem: [Incident]**\n\n**Was passiert ist:** [Kurze Beschreibung]\n**Impact:** [User/Business Impact]\n**Root Cause:** [Ursache]\n**Timeline:** [Wann detected, wann resolved]\n\n**Was wir gelernt haben:**\n1. [Learning]\n2. [Learning]\n\n**Actions:**\n- [ ] [Action + Owner + Due Date]', 4),
    (pb_id, 'Decision Request', 'decision', 'Optionen fuer Entscheider',
     'Entscheider wollen waehlen, nicht analysieren.',
     E'**Decision Needed: [Topic]**\n\n**Kontext:** [1-2 Saetze]\n\n**Option A:** [Beschreibung]\n- Pro: [X]\n- Con: [Y]\n\n**Option B:** [Beschreibung]\n- Pro: [X]\n- Con: [Y]\n\n**Empfehlung:** Option [X] weil [Grund]\n\n**Deadline:** [Date]', 5);

    -- ============ TARGETS / STAKEHOLDER TYPES ============

    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES
    (pb_id, 'Direct Manager', 'Dein direkter Vorgesetzter', 'Will keine Ueberraschungen. Frueh informieren, Loesungen vorschlagen.', 1),
    (pb_id, 'Project Sponsor', 'Budget-Owner, Executive Sponsor', 'High-Level, ROI-fokussiert, will Risiken kennen.', 2),
    (pb_id, 'Cross-functional Teams', 'Andere Teams mit Dependencies', 'Klare Timelines, fruehe Kommunikation bei Verschiebungen.', 3),
    (pb_id, 'Direct Reports', 'Deine Teammitglieder', 'Klare Erwartungen, Unterstuetzung, Blocker raeumen.', 4),
    (pb_id, 'External Partners', 'Vendors, Kunden, Agenturen', 'Professionell, schriftlich, Missverstaendnisse vermeiden.', 5);

    -- ============ STRATEGY ============

    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (pb_id, 'communication', 'Schlechte Nachrichten frueh kommunizieren', 1),
    (pb_id, 'communication', 'Mit Loesungsvorschlag kommen, nicht nur Problem', 2),
    (pb_id, 'communication', 'Regelmaessige Updates auch wenn nichts passiert', 3),
    (pb_id, 'communication', 'Kein Blame, nur Fakten und Loesungen', 4),
    (pb_id, 'documentation', 'Entscheidungen schriftlich festhalten', 1),
    (pb_id, 'documentation', 'Scope Changes dokumentieren', 2),
    (pb_id, 'documentation', 'Risiken tracken', 3),
    (pb_id, 'meetings', 'Status-Meetings kurz halten', 1),
    (pb_id, 'meetings', 'Async Status-Updates wo moeglich', 2),
    (pb_id, 'meetings', 'Entscheidungen in Meetings, nicht in Emails', 3),
    (pb_id, 'do', 'Quantifizieren (Zahlen, Daten, Fakten)', 1),
    (pb_id, 'do', 'Verantwortung uebernehmen', 2),
    (pb_id, 'do', 'Proaktiv kommunizieren', 3),
    (pb_id, 'dont', 'Probleme verstecken', 1),
    (pb_id, 'dont', 'Unrealistische Timelines versprechen', 2),
    (pb_id, 'dont', 'Blame Game spielen', 3);

    -- ============ STYLE ELEMENTS ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (pb_id, 'tone', 'Confident but Honest',
     'Selbstbewusst kommunizieren, aber ehrlich bei Problemen.',
     ARRAY['Wir sind on track', 'Hier sehe ich ein Risiko', 'Das schaffen wir, wenn X'], 1),
    (pb_id, 'structure', 'BLUF Always',
     'Bottom Line Up Front. Wichtigstes zuerst.',
     ARRAY['Status: GRUEN', 'Wir brauchen Hilfe bei X', 'Deadline verschiebt sich'], 2),
    (pb_id, 'data', 'Numbers over Feelings',
     'Quantifizieren. "80% done" statt "fast fertig".',
     ARRAY['5 von 8 Tasks done', '2 Tage Verzoegerung', '3 offene Blocker'], 3),
    (pb_id, 'ownership', 'Solution-Oriented',
     'Mit Loesungsvorschlag kommen, nicht nur Problem.',
     ARRAY['Problem X, Vorschlag Y', 'Optionen A/B/C, Empfehlung B', 'Risiko X, Mitigation Y'], 4);

END $$;
