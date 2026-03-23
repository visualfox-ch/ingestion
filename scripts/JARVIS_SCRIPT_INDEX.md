# Jarvis Script Index

Kurzindex der wichtigsten Jarvis-Helper im Ordner `scripts/`.

## Daily Operations

- `jarvis_daily_5.sh`: Zeigt die tägliche 5-Schritte-Routine (Health, Workspace, Checks, Deploy).
- `jarvis_daily_3signal.sh`: Kompakter Tagesblick auf API-Health, Container-Health und Reality-Check-Overall.
- `jarvis_predeploy_oneclick.sh`: One-click Predeploy-Flow mit Gate, Dry-Run, Health-Snapshot und Reality-Check-Baseline.
- `jarvis_self_report_consistency_check.sh`: Vergleicht Selbstaussagen (Tools/Latenz) mit Live-Endpunkten.

## Deploy Safety

- `jarvis_pre_deploy_gate.sh`: Hartes Pre-Deploy-Gate (DEPLOY_LOCK, BuildKit, Concurrency, Docs-Gate).
- `jarvis_focused_pre_deploy_tests.sh`: Führt gezielte NAS-Pre-Deploy-Tests für bekannte Codebereiche aus (py_compile + passende pytest-Suites).
- `jarvis_critical_deploy_4eyes.sh`: 4-Augen-Freigabe mit Audit-Log für kritische Deploys.
- `jarvis_safe_deploy.sh`: Orchestriert Gate -> 4-Augen -> sicheren Deploy-Zyklus mit dem kanonischen Wrapper/Build-Pfad.
- `jarvis_post_deploy_smoke.sh`: Führt gezielte Runtime-Smokes im laufenden Container nach dem Deploy aus.
- `jarvis_reality_check.sh`: Führt den kompakten PASS/WARN/FAIL-Reality-Check für Agency, Memory, Proactive und Calibration gegen die Live-API aus.
- `run_web_docs_snapshot_pilot.sh`: Führt den engen `web_docs`-NAS-Pilot gegen genau eine allowlist-Doku-Domain aus und prüft Snapshot, Source-Register und Suche.

## Docs & Hygiene

- `jarvis_docs_preflight_gate.sh`: Führt Docs-Preflight nur bei Markdown-Änderungen aus (Fallback: Full preflight).
- `sync_visualfox_claude_bridge.sh`: Spiegelt das aktuelle Claude-Visualfox-Projekt (`BRAIN-system-data`) stabil auf die NAS und kann direkt die Jarvis-Ingestion triggern.
- `repair_visualfox_bridge_scope.sh`: Repariert einen falsch nach `work_projektil` gelaufenen Visualfox-Bridge-Ingest auf der NAS und verschiebt die betroffenen Daten nach `work_visualfox`.
- `run_byterover_visualfox_core_trial.sh`: Staged den eingefrorenen `Visualfox Core Corpus v1` in einen isolierten Temp-Workspace und zeigt den lokalen ByteRover-Trial-Status plus die naechsten Provider-Schritte.
- `report_calendar_alias_usage.py`: Fragt Prometheus nach der Nutzung des Legacy-Endpoints `/n8n/calendar/events` ab und zeigt Werte pro Account für ein Lookback-Fenster.
- `refresh_web_docs_sources.py`: Aktualisiert die kuratierte `web_docs`-Quellenliste aus `web_docs_sources.json` über den bestehenden `/kb/web-docs/snapshot`-Endpoint; geeignet für Weekly Cron oder n8n.
- `web_docs_refresh_weekly.sh`: Dünner Weekly-Wrapper um `refresh_web_docs_sources.py` mit NAS-Gate, Log-Ausgabe und optionalem Dry-Run für Cron oder manuelle Läufe.
- `install_web_docs_refresh_cron.sh`: Installiert einen wöchentlichen NAS-Cronjob für den kuratierten `web_docs`-Refresh (Default: Sonntag 04:35).
- `rotate_web_docs_refresh_log.sh`: Rotiert `logs/web_docs_refresh_weekly.log` grössenbasiert (Default 10MB, Keep 5), um unbegrenztes Log-Wachstum zu vermeiden.

Retry/Resilience knobs für den Weekly-Wrapper:
- `WEB_DOCS_REFRESH_TIMEOUT` (Default `180`): Per-Source API Timeout in Sekunden.
- `WEB_DOCS_REFRESH_RETRIES` (Default `2`): Anzahl zusätzlicher Retries pro Quelle bei transienten Fehlern.
- `WEB_DOCS_REFRESH_RETRY_BACKOFF` (Default `2`): Linearer Backoff in Sekunden zwischen Retries.
- `WEB_DOCS_REFRESH_LOCK_DIR` (Default `tmp/web_docs_refresh_weekly.lock`): Einfacher Single-Run-Lock gegen parallele Cron/DSM-Starts.

## Typical Usage

```bash
# 1) Daily quick reference
./scripts/jarvis_daily_5.sh

# 2) Pre-deploy gate
./scripts/jarvis_pre_deploy_gate.sh

# 3) Targeted pre-deploy tests for touched files
TARGETED_TEST_FILES="app/jobs/maintenance_jobs.py app/services/self_knowledge.py app/prompt_assembler.py" \
  ./scripts/jarvis_pre_deploy_gate.sh

# 4) Safe deploy dry-run
SAFE_DEPLOY_DRY_RUN=1 ./scripts/jarvis_safe_deploy.sh "reason" --dry-run

# 5) Safe deploy live + targeted post-deploy smokes
POST_DEPLOY_SMOKE_FILES="app/jobs/maintenance_jobs.py app/services/self_knowledge.py app/prompt_assembler.py" \
  ./scripts/jarvis_safe_deploy.sh "reason"

# 6) Standalone post-deploy smoke
POST_DEPLOY_SMOKE_FILES="app/services/voice_tts.py app/routers/voice_router.py" \
  ./scripts/jarvis_post_deploy_smoke.sh

# 7) Standalone web_docs pilot
./scripts/run_web_docs_snapshot_pilot.sh --dry-run

# 8) Self-report consistency check
./scripts/jarvis_self_report_consistency_check.sh --claim-tools 433 --claim-latency-ms 1.6

# 9) Standalone reality check
./scripts/jarvis_reality_check.sh

# 10) ByteRover Visualfox trial helper
./scripts/run_byterover_visualfox_core_trial.sh

# 11) Legacy calendar alias usage (24h)
python3 ./scripts/report_calendar_alias_usage.py --hours 24

# 12) Refresh curated web docs (dry run)
python3 ./scripts/refresh_web_docs_sources.py --dry-run

# 13) Refresh a single docs source live
python3 ./scripts/refresh_web_docs_sources.py --only bolt_diy

# 14) Weekly wrapper dry run
WEB_DOCS_REFRESH_DRY_RUN=1 ./scripts/web_docs_refresh_weekly.sh --only qdrant_docs

# 15) Install the weekly cron job on NAS
./scripts/install_web_docs_refresh_cron.sh

# 16) Run bolt.diy with stronger retry settings (NAS)
WEB_DOCS_REFRESH_TIMEOUT=120 WEB_DOCS_REFRESH_RETRIES=4 WEB_DOCS_REFRESH_RETRY_BACKOFF=3 \
  ./scripts/web_docs_refresh_weekly.sh --only bolt_diy --fail-fast --timeout 90

# 17) Rotate weekly refresh log on demand
WEB_DOCS_REFRESH_LOG_MAX_BYTES=10485760 WEB_DOCS_REFRESH_LOG_KEEP=5 \
  /bin/bash ./scripts/rotate_web_docs_refresh_log.sh

# 18) DSM command pattern: rotate first, then run refresh
WEB_DOCS_REFRESH_LOG_MAX_BYTES=10485760 WEB_DOCS_REFRESH_LOG_KEEP=5 \
  /bin/bash ./scripts/rotate_web_docs_refresh_log.sh && \
  WEB_DOCS_REFRESH_TIMEOUT=120 WEB_DOCS_REFRESH_RETRIES=4 WEB_DOCS_REFRESH_RETRY_BACKOFF=3 \
  ./scripts/web_docs_refresh_weekly.sh --only bolt_diy --only qdrant_docs --fail-fast

# 19) Retry diagnostics proof (forces timeout retries, appends to weekly log)
WEB_DOCS_REFRESH_TIMEOUT=1 WEB_DOCS_REFRESH_RETRIES=2 WEB_DOCS_REFRESH_RETRY_BACKOFF=1 \
  /bin/bash ./scripts/web_docs_refresh_weekly.sh --only bolt_diy --fail-fast 2>&1 | tee -a ./logs/web_docs_refresh_weekly.log
```
