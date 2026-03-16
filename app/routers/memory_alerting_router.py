"""
Memory Alerting & Dashboard API
- Prometheus Health/Anomaly-Check
- Alertmanager Trigger (Telegram/Email)
- Dashboard Summary Endpoint
"""
from fastapi import APIRouter
from app.prometheus_metrics import get_prometheus_client

router = APIRouter()


@router.get(
    "/memory/alerting/health",
    summary="Memory Health Metrics",
    description="Aggregierte Health-Metriken für den Memory-Stack via Prometheus. Gibt API, System und Queue-Metriken zurück."
)
def memory_health_summary():
    """
    Liefert eine Momentaufnahme der wichtigsten Health-Metriken des Memory-Stacks (API, System, Queue) aus Prometheus.
    Beispiel-Response:
    {
        "timestamp": "2026-02-20T12:34:56",
        "prometheus_available": true,
        "api": {"response_time_p95_ms": 120, ...},
        "system": {"memory_usage_mb": 800, ...},
        "queue": {"queue_depth": 2, ...}
    }
    """
    prom = get_prometheus_client()
    return prom.get_health_summary()


@router.get(
    "/memory/alerting/anomalies",
    summary="Memory Metric Anomalies",
    description="Listet aktuelle Warnungen/Kritische Anomalien basierend auf Prometheus-Metrik-Schwellenwerten."
)
def memory_anomaly_check():
    """
    Prüft auf aktuelle Metrik-Anomalien (Warnung/Kritisch) im Memory-Stack laut Prometheus-Thresholds.
    Beispiel-Response:
    {
        "anomalies": [
            {"severity": "critical", "metric": "memory_usage", "value": 2100, ...},
            ...
        ]
    }
    """
    prom = get_prometheus_client()
    return {"anomalies": prom.detect_anomalies()}


@router.get(
    "/memory/dashboard",
    summary="Memory Dashboard (Kompakt)",
    description="Kompaktes Dashboard-JSON für UI/Grafana: Health-Metriken und aktuelle Anomalien."
)
def memory_dashboard():
    """
    Liefert ein kompaktes Dashboard-JSON für UI/Grafana mit Health-Metriken und aktuellen Anomalien.
    Beispiel-Response:
    {
        "health": { ... },
        "anomalies": [ ... ]
    }
    """
    prom = get_prometheus_client()
    return {
        "health": prom.get_health_summary(),
        "anomalies": prom.detect_anomalies(),
    }
