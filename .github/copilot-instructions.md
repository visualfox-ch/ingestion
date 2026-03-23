## Ingestion (GitHub Copilot) instructions

### Research Policy (fuer alle Agents und Subagents)

Diese Regeln gelten fuer Hauptagent, Subagents und jede Research-Aufgabe im Repo.

- Research muss sich an Best Practices orientieren, nicht an Ad-hoc-Loesungen.
- Research muss wissenschaftlich fundiert sein: belastbare Quellen, etablierte Verfahren, klare Begruendung.
- Research muss anti-overengineering sein: bevorzuge die einfachste tragfaehige Loesung.
- Keine unnötige Komplexitaet, keine speculative architecture, kein Framework-Bloat ohne klaren Bedarf.
- Wenn mehrere Loesungen tragfaehig sind, standardmaessig die waehlen, die leichter zu testen, zu betreiben und schneller zu verifizieren ist.
- Bestehende Architektur, Betriebsrealitaet und Wartbarkeit immer explizit gegen den erwarteten Nutzen abwaegen.

### Pflichtverhalten bei Research

- Erst Problem, Randbedingungen und Erfolgskriterium klaeren.
- Dann bestehende Standards, Best Practices und bewaehrte Patterns pruefen.
- Komplexitaet, Betriebsaufwand und Wartbarkeit explizit gegen den Nutzen abwaegen.
- Standardmaessig eine pragmatische Minimal-Loesung empfehlen; groessere Varianten nur als explizite Option nennen.

### Research Decision Checklist

Vor jeder Empfehlung muss der Agent kurz pruefen und explizit beantworten:

1. Was ist das konkrete Problem und das Erfolgskriterium?
2. Welche etablierte Best Practice oder welches bewaehrte Pattern deckt das bereits ab?
3. Welche Minimal-Loesung loest das Problem heute mit der geringsten zusaetzlichen Komplexitaet?
4. Welche Annahmen sind belegt und welche sind nur Vermutung?
5. Warum ist die empfohlene Loesung besser als die naechsteinfachere Alternative?
6. Welchen zusaetzlichen Betriebs-, Test- und Wartungsaufwand erzeugt die Loesung?
7. Gibt es Overengineering-Signale?
	- neue Schicht ohne klaren Bedarf
	- neues Framework ohne harten Nutzen
	- future-proofing ohne konkreten Anwendungsfall
	- Abstraktion vor validiertem Bedarf
8. Wenn Unsicherheit besteht, zuerst die reversible, kleine und gut messbare Variante empfehlen.