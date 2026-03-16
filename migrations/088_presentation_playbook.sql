-- Migration: 088_presentation_playbook
-- Presentation/Pitch Playbook: Hook-Problem-Solution structure with phrase libraries
-- Created: 2026-03-14

-- Insert Presentation Playbook
INSERT INTO content_playbooks (domain, name, version, description, purpose, golden_rule)
VALUES (
    'presentation',
    'Presentation & Pitch Playbook',
    '1.0',
    'Strukturen und Phrasen fuer Praesentationen, Pitches und Vortraege',
    'Klare Botschaft, packender Einstieg, handlungsfaehiger Abschluss',
    'Eine Kernbotschaft pro Praesentation. Wenn das Publikum nur eine Sache behaelt, welche?'
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
    sec_hooks INTEGER;
    sec_bridges INTEGER;
    sec_evidence INTEGER;
    sec_cta INTEGER;
    sec_qa INTEGER;
    tg_tech INTEGER;
    tg_business INTEGER;
    tg_investors INTEGER;
BEGIN
    SELECT id INTO pb_id FROM content_playbooks WHERE domain = 'presentation' LIMIT 1;

    -- ============ FORMULAS ============

    INSERT INTO content_playbook_formulas (playbook_id, name, formula, example)
    VALUES
    (pb_id, 'Hook-Problem-Solution',
     'Hook (Attention) → Problem (Pain) → Solution (Your Idea) → Evidence (Proof) → CTA (Action)',
     'Was waere, wenn ich euch sage, dass 80% aller Praesentationen in den ersten 30 Sekunden verloren gehen? (Hook) Das Problem: Wir starten mit Agenda-Folien. (Problem) Stattdessen: Ein starker Hook. (Solution) In meinen letzten 20 Pitches hat das die Engagement-Rate verdoppelt. (Evidence) Probiert es bei eurem naechsten Pitch aus. (CTA)'),
    (pb_id, 'Story Arc',
     'Status Quo → Disruption → Struggle → Discovery → Resolution',
     'Vor einem Jahr hatten wir ein Problem... (Status Quo) Dann passierte X... (Disruption) Wir haben alles versucht... (Struggle) Bis wir entdeckten... (Discovery) Heute sind wir hier. (Resolution)'),
    (pb_id, 'Problem-Agitation-Solution',
     'Problem (identify) → Agitation (make it hurt) → Solution (relief)',
     'Deadlines werden verpasst. (Problem) Das kostet nicht nur Geld - es kostet Vertrauen, Schlaf, manchmal Jobs. (Agitation) Hier ist wie wir das geloest haben. (Solution)');

    -- ============ SECTIONS + PHRASES ============

    -- Hook / Opening
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'hooks', 'Hooks & Openings', 'Aufmerksamkeit in den ersten 30 Sekunden', 'Allererster Satz der Praesentation', 1)
    RETURNING id INTO sec_hooks;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    -- Question hooks
    (sec_hooks, 'Was waere, wenn ich euch sage, dass...?', 'question'),
    (sec_hooks, 'Wer von euch hat schon mal...?', 'question'),
    (sec_hooks, 'Stellt euch vor...', 'imagination'),
    (sec_hooks, 'Habt ihr euch je gefragt, warum...?', 'question'),
    -- Statistic hooks
    (sec_hooks, '[Zahl]%. Das ist [was diese Zahl bedeutet].', 'statistic'),
    (sec_hooks, 'Jeden Tag passiert X - und die meisten wissen es nicht.', 'statistic'),
    (sec_hooks, 'In den naechsten [Zeitraum] wird [ueberraschende Prognose].', 'statistic'),
    -- Story hooks
    (sec_hooks, 'Vor [Zeitraum] hatten wir ein Problem...', 'story'),
    (sec_hooks, 'Letzte Woche ist etwas Interessantes passiert...', 'story'),
    (sec_hooks, 'Ich erinnere mich an den Moment, als...', 'story'),
    -- Contrarian hooks
    (sec_hooks, 'Alles was ihr ueber X wisst, ist falsch.', 'contrarian'),
    (sec_hooks, 'Die meisten Leute denken X. Die Realitaet ist Y.', 'contrarian'),
    (sec_hooks, 'Vergesst alles, was ihr ueber X gehoert habt.', 'contrarian'),
    -- Direct hooks
    (sec_hooks, 'Ich bin hier um euch zu zeigen, wie ihr [konkreter Benefit].', 'direct'),
    (sec_hooks, 'In den naechsten [Zeit] werdet ihr lernen...', 'direct');

    -- Transitions / Bridges
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'bridges', 'Uebergaenge & Bridges', 'Fluessige Verbindungen zwischen Abschnitten', 'Zwischen Slides/Themen', 2)
    RETURNING id INTO sec_bridges;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_bridges, 'Das bringt mich zu...', 'forward'),
    (sec_bridges, 'Aber was bedeutet das konkret?', 'deepening'),
    (sec_bridges, 'Jetzt wird es interessant...', 'energy'),
    (sec_bridges, 'Hier kommt der Punkt, an dem alles zusammenkommt.', 'synthesis'),
    (sec_bridges, 'Das war das Problem. Jetzt zur Loesung.', 'pivot'),
    (sec_bridges, 'Warum erzaehle ich euch das?', 'relevance'),
    (sec_bridges, 'Lasst mich das an einem Beispiel zeigen.', 'example'),
    (sec_bridges, 'Ihr fragt euch vielleicht...', 'anticipate'),
    (sec_bridges, 'Kurze Pause hier. Das ist wichtig.', 'emphasis'),
    (sec_bridges, 'Behaltet das im Kopf - wir kommen darauf zurueck.', 'foreshadowing');

    -- Evidence / Proof
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'evidence', 'Evidence & Proof Points', 'Glaubwuerdigkeit aufbauen', 'Nach Solution, vor CTA', 3)
    RETURNING id INTO sec_evidence;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_evidence, 'Hier ist ein konkretes Beispiel...', 'case_study'),
    (sec_evidence, 'Wir haben das bei [Kunde/Projekt] umgesetzt...', 'case_study'),
    (sec_evidence, 'Die Zahlen sprechen fuer sich: [Ergebnis].', 'data'),
    (sec_evidence, 'In einer Studie von [Quelle] wurde gezeigt...', 'research'),
    (sec_evidence, 'Das ist nicht nur Theorie. [Beweis].', 'proof'),
    (sec_evidence, 'Andere haben das auch bestaetigt: [Referenz].', 'social_proof'),
    (sec_evidence, 'Vorher: [Zustand]. Nachher: [Ergebnis].', 'before_after'),
    (sec_evidence, 'Selbst [skeptische Partei] hat zugegeben...', 'credibility');

    -- Call to Action
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'cta', 'Call to Action', 'Klare Handlungsaufforderung', 'Letzter Teil der Praesentation', 4)
    RETURNING id INTO sec_cta;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_cta, 'Was ich von euch brauche ist...', 'direct'),
    (sec_cta, 'Der naechste Schritt waere...', 'incremental'),
    (sec_cta, 'Wenn ihr eine Sache mitnehmt, dann diese: [Kernbotschaft].', 'takeaway'),
    (sec_cta, 'Ich lade euch ein, [konkrete Aktion].', 'invitation'),
    (sec_cta, 'Lasst uns [gemeinsame Aktion].', 'collaborative'),
    (sec_cta, 'Die Frage ist nicht ob, sondern wann.', 'urgency'),
    (sec_cta, 'Wer ist dabei?', 'commitment'),
    (sec_cta, 'Probiert es diese Woche aus und berichtet mir.', 'experiment');

    -- Q&A Handling
    INSERT INTO content_playbook_sections (playbook_id, section_key, section_name, description, usage_context, sort_order)
    VALUES (pb_id, 'qa', 'Q&A Handling', 'Souveraen mit Fragen umgehen', 'Nach der Praesentation', 5)
    RETURNING id INTO sec_qa;

    INSERT INTO content_playbook_phrases (section_id, phrase, category) VALUES
    (sec_qa, 'Gute Frage. [Antwort].', 'acknowledge'),
    (sec_qa, 'Das hoere ich oft. [Antwort].', 'normalize'),
    (sec_qa, 'Lass mich das kurz einordnen...', 'context'),
    (sec_qa, 'Kurze Antwort: [X]. Lange Antwort: [Details].', 'structure'),
    (sec_qa, 'Das ist ein wichtiger Punkt. [Antwort].', 'validate'),
    (sec_qa, 'Dazu habe ich keine Daten, aber meine Einschaetzung ist...', 'honest'),
    (sec_qa, 'Das geht ueber den Scope hinaus, aber gerne nach dem Talk.', 'defer'),
    (sec_qa, 'Um das richtig zu beantworten, muesste ich wissen...', 'clarify');

    -- ============ FORBIDDEN PHRASES ============

    INSERT INTO content_playbook_forbidden (playbook_id, phrase, reason) VALUES
    (pb_id, 'Ich freue mich, heute hier zu sein', 'Leerer Opener, verschwendet Zeit'),
    (pb_id, 'Koennt ihr mich hinten hoeren?', 'Zeigt Unsicherheit, unprofessionell'),
    (pb_id, 'Ich bin ein bisschen nervoes', 'Untergabt Autoritaet'),
    (pb_id, 'Das ist wahrscheinlich langweilig, aber...', 'Selbstsabotage'),
    (pb_id, 'Ich weiss, dass ihr das schon wisst...', 'Entwertet eigene Inhalte'),
    (pb_id, 'Auf dieser Folie sieht man...', 'Liest Folien vor'),
    (pb_id, 'Das ist ziemlich komplex...', 'Entschuldigung statt Erklaerung'),
    (pb_id, 'Ich werde versuchen schnell zu machen', 'Signalisiert schlechte Vorbereitung'),
    (pb_id, 'Hat jemand noch Fragen?', 'Zu passiv - besser: Welche Fragen habt ihr?'),
    (pb_id, 'Ich denke, das wars', 'Schwaches Ende');

    -- ============ POST TYPES / FORMATS ============

    INSERT INTO content_playbook_post_types (playbook_id, type_name, type_key, description, why_it_works, example_post, sort_order) VALUES
    (pb_id, 'Lightning Talk', 'lightning', '5-10 Minuten, ein Punkt, kein Bullshit',
     'Zwingt zur Klarheit. Respektiert Zeit des Publikums.',
     'Hook (30s) → Problem (1m) → Solution (2m) → Example (1m) → CTA (30s)', 1),
    (pb_id, 'Technical Deep Dive', 'technical', '20-45 Minuten, technisches Publikum, Details erlaubt',
     'Zeigt Expertise. Baut Vertrauen bei Fachleuten.',
     'Context (2m) → Architecture (5m) → Implementation (10m) → Learnings (5m) → Q&A (10m)', 2),
    (pb_id, 'Executive Pitch', 'executive', '10-15 Minuten, Entscheider, ROI-fokussiert',
     'Zeitdruck-optimiert. Entscheidungsorientiert.',
     'Problem (2m) → Impact (2m) → Solution (3m) → ROI (2m) → Ask (1m)', 3),
    (pb_id, 'Keynote', 'keynote', '30-60 Minuten, inspirierend, Story-driven',
     'Baut emotionale Verbindung. Bleibt in Erinnerung.',
     'Personal Hook (3m) → Context (5m) → 3 Main Points (je 10m) → Synthesis (5m) → Inspirational Close (3m)', 4);

    -- ============ TARGETS ============

    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (pb_id, 'Technical Audience', 'Entwickler, Engineers, Technical Leads', 'Wollen Details, Skeptisch gegenueber Buzzwords, schaetzen Ehrlichkeit', 1)
    RETURNING id INTO tg_tech;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, notes) VALUES
    (tg_tech, 'Entwickler-Teams', 'group', 'Code-Beispiele, Architektur-Diagramme, "Show dont tell"'),
    (tg_tech, 'CTOs / Tech Leads', 'role', 'Strategic + Technical, Trade-offs betonen'),
    (tg_tech, 'DevOps / SRE', 'role', 'Operational concerns, Reliability, Monitoring');

    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (pb_id, 'Business Audience', 'Product Manager, Marketing, Sales, Ops', 'Wollen Outcomes, nicht Implementation. ROI > Features.', 2)
    RETURNING id INTO tg_business;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, notes) VALUES
    (tg_business, 'Product Manager', 'role', 'User Value, Roadmap Impact, Prioritization'),
    (tg_business, 'Marketing / Sales', 'role', 'Customer Stories, Competitive Advantage, Easy-to-explain'),
    (tg_business, 'Operations', 'role', 'Efficiency Gains, Process Changes, Training Needs');

    INSERT INTO content_playbook_targets (playbook_id, group_name, group_description, why_important, sort_order)
    VALUES (pb_id, 'Investors / Executives', 'C-Level, VCs, Board Members', 'Wenig Zeit, grosse Entscheidungen. Klarheit > Details.', 3)
    RETURNING id INTO tg_investors;

    INSERT INTO content_playbook_target_accounts (target_group_id, account_name, account_type, notes) VALUES
    (tg_investors, 'C-Level', 'role', 'Strategic Impact, Risk, Resource Needs'),
    (tg_investors, 'VCs / Investors', 'role', 'Market Size, Traction, Team, Exit'),
    (tg_investors, 'Board Members', 'role', 'Governance, Long-term, Accountability');

    -- ============ STRATEGY ============

    INSERT INTO content_playbook_strategy (playbook_id, category, guideline, priority) VALUES
    (pb_id, 'preparation', 'Kernbotschaft in einem Satz formulieren koennen', 1),
    (pb_id, 'preparation', 'Publikum vorher recherchieren', 2),
    (pb_id, 'preparation', '3x laut durchsprechen vor dem Pitch', 3),
    (pb_id, 'preparation', 'Backup-Plan wenn Technik versagt', 4),
    (pb_id, 'structure', 'Max 1 Idee pro Folie', 1),
    (pb_id, 'structure', 'Weniger Text, mehr Visuals', 2),
    (pb_id, 'structure', 'Slides sind Prompter, nicht Script', 3),
    (pb_id, 'delivery', 'Pausen sind dein Freund', 1),
    (pb_id, 'delivery', 'Augenkontakt in alle Richtungen', 2),
    (pb_id, 'delivery', 'Energie 20% hoeher als normal', 3),
    (pb_id, 'delivery', 'Bewegung mit Absicht, nicht aus Nervositaet', 4),
    (pb_id, 'do', 'Mit starkem Hook starten', 1),
    (pb_id, 'do', 'Stories und Beispiele nutzen', 2),
    (pb_id, 'do', 'Klares CTA am Ende', 3),
    (pb_id, 'dont', 'Folien vorlesen', 1),
    (pb_id, 'dont', 'Sich entschuldigen', 2),
    (pb_id, 'dont', 'Ueberziehen', 3);

    -- ============ STYLE ELEMENTS ============

    INSERT INTO content_playbook_style_elements (playbook_id, element_type, element_name, description, examples, sort_order) VALUES
    (pb_id, 'energy', 'Controlled Energy',
     'Enthusiastisch aber nicht ueberdreht. Pausen fuer Emphasis.',
     ARRAY['Langsamer reden bei wichtigen Punkten', 'Stille nach key statements'], 1),
    (pb_id, 'language', 'Konkret statt Abstrakt',
     'Beispiele > Konzepte. Zahlen > Adjektive.',
     ARRAY['Nicht: "signifikante Verbesserung" - Sondern: "40% schneller"', 'Nicht: "viele Kunden" - Sondern: "47 Enterprise-Kunden"'], 2),
    (pb_id, 'structure', 'Rule of Three',
     'Drei Punkte sind merkbar. Fuenf nicht.',
     ARRAY['Drei Hauptargumente', 'Drei Beispiele', 'Drei Takeaways'], 3),
    (pb_id, 'authenticity', 'Ehrlich bei Unsicherheit',
     'Lieber "Ich weiss es nicht" als Bullshit.',
     ARRAY['Das muesste ich nachschauen', 'Gute Frage - dazu habe ich keine Daten'], 4);

END $$;
