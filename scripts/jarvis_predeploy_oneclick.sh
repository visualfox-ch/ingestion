#!/usr/bin/env bash
set -euo pipefail

# One-click pre-deploy verification:
# 1) Pre-deploy gate
# 2) Safe deploy dry-run
# 3) Compact health snapshot
# 4) Reality-check baseline against the currently running runtime

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

REASON="${1:-predeploy-oneclick-verify}"
NAS_DOCKER_ROOT="/volume1/BRAIN/system/docker"

echo "[oneclick] root=$ROOT"
echo "[oneclick] nas_host=$NAS_HOST"
echo "[oneclick] reason=$REASON"

echo "[oneclick] Step 1/4: pre-deploy gate"
run_host_cmd "cd $NAS_DOCKER_ROOT && ./scripts/jarvis_pre_deploy_gate.sh"

echo "[oneclick] Step 2/4: safe deploy dry-run"
run_host_cmd "cd $NAS_DOCKER_ROOT && SAFE_DEPLOY_DRY_RUN=1 ./scripts/jarvis_safe_deploy.sh \"$REASON\" --dry-run"

echo "[oneclick] Step 3/4: health snapshot"
api_code="$(run_host_cmd "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/health || echo 000" | tr -d '\r' | grep -E '^[0-9]{3}$' | tail -n 1 || true)"
[[ -n "$api_code" ]] || api_code="000"

container_health="$(run_host_cmd "if [ -x /usr/local/bin/docker ]; then D=/usr/local/bin/docker; elif [ -x /var/packages/ContainerManager/target/usr/bin/docker ]; then D=/var/packages/ContainerManager/target/usr/bin/docker; else D=docker; fi; \$D inspect --format '{{.State.Health.Status}}' jarvis-ingestion 2>/dev/null || echo unknown" | tr -d '\r' | grep -E '^(healthy|unhealthy|starting|none|unknown)$' | tail -n 1 || true)"
[[ -n "$container_health" ]] || container_health="unknown"

lock_state="$(run_host_cmd "if [ -f /tmp/jarvis-deploy.lock ]; then p=\$(cat /tmp/jarvis-deploy.lock 2>/dev/null || true); if [ -n \"\$p\" ] && kill -0 \"\$p\" 2>/dev/null; then echo active:\$p; else echo stale; fi; else echo clear; fi" | tr -d '\r' | grep -E '^(clear|stale|active:[0-9]+)$' | tail -n 1 || true)"
[[ -n "$lock_state" ]] || lock_state="unknown"

echo ""
echo "[oneclick] Snapshot"
echo "  api_health_http: $api_code"
echo "  ingestion_health: $container_health"
echo "  deploy_lock:      $lock_state"

echo ""
echo "[oneclick] Step 4/4: reality-check baseline"
run_host_cmd "cd $NAS_DOCKER_ROOT && bash ./scripts/jarvis_reality_check.sh"

echo "[oneclick] PASS"
