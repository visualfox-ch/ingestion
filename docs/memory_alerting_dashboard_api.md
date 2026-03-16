# Memory Alerting & Dashboard API Usage

This document describes the new endpoints for memory health, alerting, and dashboard integration, powered by Prometheus metrics.

## Endpoints

### 1. `/memory/alerting/health`
- **Method:** GET
- **Description:** Aggregierte Health-Metriken für den Memory-Stack (API, System, Queue) via Prometheus.
- **Response Example:**
```json
{
  "timestamp": "2026-02-20T12:34:56",
  "prometheus_available": true,
  "api": {"response_time_p95_ms": 120, "request_rate_per_sec": 2.1, "error_rate": 0.0},
  "system": {"memory_usage_mb": 800, "cpu_usage_percent": 12.5},
  "queue": {"queue_depth": 2, "db_pool_utilization": 5}
}
```

### 2. `/memory/alerting/anomalies`
- **Method:** GET
- **Description:** Listet aktuelle Warnungen/Kritische Anomalien basierend auf Prometheus-Metrik-Schwellenwerten.
- **Response Example:**
```json
{
  "anomalies": [
    {"severity": "critical", "metric": "memory_usage", "value": 2100, "threshold": 2000, "message": "memory_usage: 2100.00 MB (critical: 2000)"}
  ]
}
```

### 3. `/memory/dashboard`
- **Method:** GET
- **Description:** Kompaktes Dashboard-JSON für UI/Grafana: Health-Metriken und aktuelle Anomalien.
- **Response Example:**
```json
{
  "health": { ... },
  "anomalies": [ ... ]
}
```

## Integration
- Alle Endpoints liefern JSON und sind für Monitoring, Alerting und UI-Dashboards geeignet.
- Anomalie-Detection basiert auf in `prometheus_metrics.py` definierten Schwellenwerten.
- Für Alertmanager-Integration können die Anomalien-Responses als Trigger genutzt werden.

---
Letzte Änderung: 20.02.2026
