#!/usr/bin/env bash
set -euo pipefail

# Compact daily status with exactly 3 core signals:
# 1) API health
# 2) Container health
# 3) Reality-check overall status

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/lib/ssh.sh
source "$ROOT/scripts/lib/ssh.sh"

if [[ -z "${NAS_HOST:-}" ]]; then
  if [[ -d /volume1/BRAIN/system/docker ]]; then
    NAS_HOST="localhost"
  else
    NAS_HOST="jarvis-vscode"
  fi
fi

api_code="$(run_host_cmd "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/health || echo 000" | tr -d '\r' | grep -E '^[0-9]{3}$' | tail -n 1 || true)"
[[ -n "$api_code" ]] || api_code="000"

container_health="$(run_host_cmd "if [ -x /usr/local/bin/docker ]; then D=/usr/local/bin/docker; elif [ -x /var/packages/ContainerManager/target/usr/bin/docker ]; then D=/var/packages/ContainerManager/target/usr/bin/docker; else D=docker; fi; \$D inspect --format '{{.State.Health.Status}}' jarvis-ingestion 2>/dev/null || echo unknown" | tr -d '\r' | grep -E '^(healthy|unhealthy|starting|none|unknown)$' | tail -n 1 || true)"
[[ -n "$container_health" ]] || container_health="unknown"

lock_state="$(run_host_cmd "if [ -f /tmp/jarvis-deploy.lock ]; then p=\$(cat /tmp/jarvis-deploy.lock 2>/dev/null || true); if [ -n \"\$p\" ] && kill -0 \"\$p\" 2>/dev/null; then echo active:\$p; else echo stale; fi; else echo clear; fi" | tr -d '\r' | grep -E '^(clear|stale|active:[0-9]+)$' | tail -n 1 || true)"
[[ -n "$lock_state" ]] || lock_state="unknown"

reality_output="$(run_host_cmd "cd /volume1/BRAIN/system/docker && bash ./scripts/jarvis_reality_check.sh" 2>&1 || true)"
reality_overall="$(printf '%s\n' "$reality_output" | sed -n 's/^overall:[[:space:]]*\(.*\)$/\1/p' | tail -n 1 || true)"
[[ -n "$reality_overall" ]] || reality_overall="unknown"

status_api="OK"
[[ "$api_code" == "200" ]] || status_api="WARN"

status_container="OK"
[[ "$container_health" == "healthy" ]] || status_container="WARN"

status_reality="OK"
[[ "$reality_overall" == "pass" || "$reality_overall" == "warn" ]] || status_reality="WARN"

echo "Jarvis Daily 3-Signal"
echo "timestamp: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "nas_host:   $NAS_HOST"
echo ""
printf '1) %-17s = %-12s (%s)\n' "api_health_http" "$api_code" "$status_api"
printf '2) %-17s = %-12s (%s)\n' "ingestion_health" "$container_health" "$status_container"
printf '3) %-17s = %-12s (%s)\n' "reality_overall" "$reality_overall" "$status_reality"

if [[ "$status_api" == "OK" && "$status_container" == "OK" && "$status_reality" == "OK" ]]; then
  echo ""
  echo "overall: OK"
else
  echo ""
  echo "overall: WARN"
fi

if [[ "$lock_state" != "clear" && "$lock_state" != "stale" ]]; then
  echo "note: deploy_lock=$lock_state"
fi
