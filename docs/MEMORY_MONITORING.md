# Memory-Stack Monitoring & Observability

## Neue Endpunkte

- **Prometheus Metrics:** `/memory/metrics`  
  → Exportiert alle Memory-spezifischen Prometheus-Metriken (Reads, Writes, Errors, Latenz, Health).
- **Health-Check:** `/memory/health`  
  → Gibt den aktuellen Health-Status des Memory-Stacks (inkl. Redis) zurück.

## Integration
- Die neuen Endpunkte sind im FastAPI-Startup (`main.py`) automatisch registriert.
- Prometheus-kompatibel: `/memory/metrics` kann direkt von Prometheus/Grafana gescraped werden.
- Health-Check kann für Monitoring, Alerting und Self-Healing genutzt werden.

## Beispiel-Metriken
- `jarvis_memory_reads_total` — Anzahl Memory-Reads
- `jarvis_memory_writes_total` — Anzahl Memory-Writes
- `jarvis_memory_errors_total` — Fehler bei Memory-Operationen
- `jarvis_memory_latency_seconds` — Latenzverteilung
- `jarvis_memory_health` — 1=healthy, 0=unhealthy

## Hinweise
- Für eigene Memory-Operationen: Counter/Histogram im Code nutzen (siehe Kommentar in `memory_metrics_router.py`).
- Health-Check prüft Redis-Verfügbarkeit und setzt Gauge entsprechend.

---
Letztes Update: 2026-02-20
