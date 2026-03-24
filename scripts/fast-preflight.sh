#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CANONICAL_OPS_ROOT="${JARVIS_CANONICAL_OPS_ROOT:-/Volumes/BRAIN/system/docker}"
CANONICAL_FAST_PREFLIGHT="$CANONICAL_OPS_ROOT/scripts/fast-preflight.sh"

if [[ -f "$CANONICAL_FAST_PREFLIGHT" ]]; then
  exec bash "$CANONICAL_FAST_PREFLIGHT"
fi

START_TIME=$(date +%s)

echo "⚡ Fast Parallel Preflight (ingestion fallback)"
echo "==============================================="
echo "Canonical preflight not found at: $CANONICAL_FAST_PREFLIGHT"
echo "Running local fallback governance checks..."

GOV_OUT=$(python3 "$ROOT_DIR/scripts/check_session_prompt_governance.py" 2>&1 || true)

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

if [[ "$GOV_OUT" == "PASS" ]]; then
  echo "Results (${DURATION}s):"
  echo "  ✅ Session prompt governance: OK"
  echo "✅ Preflight PASSED (${DURATION}s)"
  exit 0
fi

echo "Results (${DURATION}s):"
FIRST_FAIL=$(echo "$GOV_OUT" | grep -E "^FAIL:" | head -1)
if [[ -z "$FIRST_FAIL" ]]; then
  FIRST_FAIL="FAIL:unknown"
fi
echo "  ❌ Session prompt governance: ${FIRST_FAIL#FAIL:}"
echo "❌ Preflight FAILED (${DURATION}s)"
exit 1
