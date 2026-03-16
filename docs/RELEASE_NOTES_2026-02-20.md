# Release Notes – Memory-Stack & Monitoring

## 2026-02-20

### Features
- **Memory-Stack:**
  - Modularisierung: `MemoryFact`, Retrieval, Tagging, Confidence, MemoryStore
  - End-to-End-Tests und Integrationstests für alle Memory-Features
  - Verbesserte Fehlerbehandlung und Logging
- **Monitoring & Observability:**
  - Prometheus-kompatible Metriken für Reads, Writes, Errors, Latenz, Health
  - Health-Check-Endpoint `/memory/health` für Monitoring und Self-Healing
  - Dokumentation: `docs/MEMORY_MONITORING.md`

### Refactoring
- Code-Review und Cleanup der Memory-Module
- Logging-Strategie vereinheitlicht

### Hinweise
- Prometheus-Endpunkt `/memory/metrics` kann direkt gescraped werden
- Health-Check prüft Redis und Memory-Stack
- Für eigene Memory-Operationen: Prometheus-Counter/Histogram im Code nutzen

---
Letztes Update: 2026-02-20
