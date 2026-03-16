# Grafana Dashboard & Alerting: Sandbox & Self-Testing (Best Practice)

## Ziel
Transparente Überwachung und Alerting für Sandbox-Executions, Self-Tests und Policy-Compliance im Jarvis-System.

## Dashboard Panels (Empfehlung)
- **Sandbox Executions (by Mode/Status):**
  - Panel: `sum by (mode, status) (jarvis_sandbox_executions_total)`
  - Visualisierung: Stacked Bar/Time Series
  - Zeigt: Verteilung und Trends nach Modus (native/docker/firejail) und Status (success/error/timeout)
- **Sandbox Execution Duration:**
  - Panel: `histogram_quantile(0.95, sum(rate(jarvis_sandbox_execution_duration_seconds_bucket[5m])) by (le, mode))`
  - Visualisierung: Line/Heatmap
  - Zeigt: 95th Percentile Ausführungsdauer pro Modus
- **Self-Test Status:**
  - Panel: `sum by (test, status) (jarvis_self_tests_total)`
  - Visualisierung: Table/Bar
  - Zeigt: Health, DB, Sandbox, Metrics-Check (Status/Fehler)
- **Sandbox Errors/Timeouts:**
  - Panel: `sum by (mode) (jarvis_sandbox_executions_total{status=~"error|timeout"})`
  - Visualisierung: Bar/Alert
- **Recent Executions (Audit):**
  - Table-Panel mit Audit-Log-Auszügen (exec_id, user, code_hash, status, mode, duration)

## Alerts (Empfehlung)
- **Sandbox Error Rate:**
  - Alert: `increase(jarvis_sandbox_executions_total{status="error"}[5m]) > 3`
  - Action: Telegram/Email/Slack
- **Sandbox Timeout Spike:**
  - Alert: `increase(jarvis_sandbox_executions_total{status="timeout"}[5m]) > 2`
- **Self-Test Failure:**
  - Alert: `increase(jarvis_self_tests_total{status!="success"}[10m]) > 0`
- **Policy Violation (Audit):**
  - Alert: Audit-Log mit status=blocked oder blocked_reason gesetzt

## Best Practices
- Panels und Alerts immer nach Modus (mode) und Status aufschlüsseln
- Audit-Log als Table-Panel für Forensik
- Alerts mit dedizierten Runbooks/Links zur Policy
- Self-Test-Panel prominent platzieren (Ampel/Status)
- Policy-Änderungen versionieren und dokumentieren

---
Letztes Update: 2026-02-10
