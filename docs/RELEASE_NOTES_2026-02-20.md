# Release Notes – Memory-Stack & Monitoring

## 2026-03-19

### Stabilization Hotfixes
- Telegram runtime stabilized by fixing PostgreSQL cursor usage (`get_cursor` -> `get_dict_cursor`) in dict-based read paths.
- Audit trail startup fixed:
  - migrated legacy `safe_write_query`/`safe_list_query` direct calls to context-manager usage.
  - corrected PostgreSQL schema SQL for `approval_audit_log` (moved inline index syntax to `CREATE INDEX IF NOT EXISTS`).
- Decision tracking schema compatibility fixed via migration `123_decision_log_outcome_fields.sql`:
  - added `outcome_score`, `outcome_notes`, `resolved_at`, `outcome_verified` on `decision_log`.
- n8n integration restored:
  - synchronized `N8N_API_KEY` with active n8n API key.
  - verified `n8n_workflow_manager.list_workflows()` from ingestion runtime.

### Startup Behavior Improvement
- Embedding model preload now supports non-blocking startup mode (default):
  - `EMBEDDING_PRELOAD_MODE=background` (default) starts preload in daemon thread.
  - `EMBEDDING_PRELOAD_MODE=sync` keeps legacy blocking behavior.

### Runbook Note (n8n API 401)
- Symptom: `n8n API request failed` with `HTTP 401 unauthorized` on `/workflows`.
- Quick fix:
  - verify active n8n key against `http://127.0.0.1:25678/api/v1/workflows` using `X-N8N-API-KEY`.
  - update `N8N_API_KEY` in `/volume1/BRAIN/system/docker/.env`.
  - reload ingestion service and re-verify via in-container `N8NWorkflowManager().list_workflows()`.

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
