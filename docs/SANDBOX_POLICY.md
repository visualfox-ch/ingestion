# Jarvis Sandbox Policy & Security

## Ziel
Sichere, nachvollziehbare Ausführung von Code (Self-Tests, User-Code, Agenten) mit maximaler Transparenz und minimalem Risiko für das Host-System.

## Sandbox-Architektur
- **Modi:** native (default), docker, firejail (umschaltbar via JARVIS_PYTHON_SANDBOX_MODE)
- **Isolation:**
  - native: Subprozess, Arbeitsverzeichnis, Ressourcenlimits
  - docker: Container (python:3.11-slim), kein Netzwerk, Memory/CPU-Limit, gemountetes Workdir
  - firejail: Private FS, kein Netzwerk, Memory/CPU-Limit
- **Whitelisting:** Nur explizit erlaubte Python-Imports und -Funktionen
- **Blacklisting:** Verbotene Patterns (os, subprocess, Shell, FS-Operationen, Netzwerk, etc.)
- **Timeouts:** Max. Ausführungszeit (konfigurierbar)
- **Output-Limits:** Max. Output/Artefaktgröße
- **Audit:** Jede Ausführung (auch blockiert/fehlerhaft) wird mit Code, User, Modus, Status, Zeit, Artefakten geloggt
- **Prometheus:** Metriken für Ausführungen, Fehler, Modus, Dauer

## Security Controls
- Kein Netzwerkzugriff (docker: --network none, firejail: --net=none)
- Kein Zugriff auf Host-Dateien außerhalb Whitelist
- Keine Shell- oder Systemaufrufe
- Ressourcenlimits (Memory, CPU, Output)
- Artefakt-Handling (z. B. Bilder) nur im Workdir
- Policy-Bypass nur mit explizitem Admin-Override

## Recovery & Monitoring
- Audit-Logs für jede Ausführung (JSON, Code, Metadaten)
- Prometheus/Grafana für Monitoring, Alerting, Forensik
- Self-Test-API prüft Sandbox-Funktion und Policy-Compliance
- Alerts bei Policy-Verletzung, Fehler, Ausführungsanomalien

## Erweiterung
- VM/Container-Integration für noch stärkere Isolation
- Policy-Update via Admin-API
- Automatisierte Security-Tests (Self-Test-API)

---
Letztes Update: 2026-02-10
