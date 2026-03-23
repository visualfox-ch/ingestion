#!/usr/bin/env bash
set -euo pipefail

NAS_ROOT="/volume1/BRAIN/system/docker"
ROOT="${JARVIS_DOCKER_ROOT:-}"
ALLOW_NON_NAS="${ALLOW_NON_NAS:-0}"
API_BASE="${JARVIS_API_BASE:-http://localhost:18000}"
DRY_RUN=0
HOURS="${REALITY_CHECK_HOURS:-168}"
DAYS="${REALITY_CHECK_DAYS:-7}"
USER_ID="${REALITY_CHECK_USER_ID:-}"
WARN_AS_FAIL="${REALITY_CHECK_WARN_AS_FAIL:-0}"
PRINT_JSON=0
API_KEY="${JARVIS_API_KEY:-}"
API_KEY_HEADER_NAME="${JARVIS_API_KEY_HEADER:-X-API-Key}"

fail() {
  echo "[reality-check] FAIL: $1" >&2
  exit 1
}

info() {
  echo "[reality-check] $1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --hours)
      HOURS="$2"
      shift 2
      ;;
    --days)
      DAYS="$2"
      shift 2
      ;;
    --user-id)
      USER_ID="$2"
      shift 2
      ;;
    --warn-as-fail)
      WARN_AS_FAIL=1
      shift
      ;;
    --print-json)
      PRINT_JSON=1
      shift
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

if [[ "$ALLOW_NON_NAS" != "1" ]]; then
  if [[ "$(uname -s)" != "Linux" || ! -d "$NAS_ROOT" ]]; then
    fail "Reality check must run on NAS Linux. Use ALLOW_NON_NAS=1 only for local dry-runs."
  fi
fi

if [[ -z "$ROOT" ]]; then
  if [[ -d "$NAS_ROOT" ]]; then
    ROOT="$NAS_ROOT"
  else
    ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  fi
fi

if [[ ! -d "$ROOT" ]]; then
  fail "Repo root not found: $ROOT"
fi
cd "$ROOT"

if [[ -z "$API_KEY" && -f "$ROOT/.env" ]]; then
  API_KEY="$(grep -E '^JARVIS_API_KEY=' "$ROOT/.env" | head -n 1 | cut -d= -f2- || true)"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  info "DRY RUN"
  info "api_base=$API_BASE"
  info "hours=$HOURS days=$DAYS user_id=${USER_ID:-none} warn_as_fail=$WARN_AS_FAIL"
  info "would query: /health /livez /readyz /self/reality-check-snapshot"
  exit 0
fi

request_code() {
  local path="$1"
  local url="${API_BASE}${path}"
  local tmp
  tmp="$(mktemp)"
  local code
  local -a curl_args
  curl_args=(-sS -m 10 -o "$tmp" -w '%{http_code}')
  if [[ -n "$API_KEY" ]]; then
    curl_args+=(-H "${API_KEY_HEADER_NAME}: ${API_KEY}")
  fi
  code="$(curl "${curl_args[@]}" "$url" || true)"
  cat "$tmp"
  rm -f "$tmp"
  printf '\n__HTTP_CODE__:%s\n' "$code"
}

health_raw="$(request_code "/health")"
livez_raw="$(request_code "/livez")"
readyz_raw="$(request_code "/readyz")"

extract_code() {
  printf '%s' "$1" | sed -n 's/^__HTTP_CODE__:\([0-9][0-9][0-9]\)$/\1/p' | tail -n 1
}

extract_body() {
  printf '%s' "$1" | sed '/^__HTTP_CODE__:/d'
}

health_code="$(extract_code "$health_raw")"
livez_code="$(extract_code "$livez_raw")"
readyz_code="$(extract_code "$readyz_raw")"

[[ "$health_code" == "200" ]] || fail "/health returned ${health_code:-unknown}"
[[ "$livez_code" == "200" ]] || fail "/livez returned ${livez_code:-unknown}"
[[ "$readyz_code" == "200" ]] || fail "/readyz returned ${readyz_code:-unknown}"

snapshot_path="/self/reality-check-snapshot?hours=${HOURS}&days=${DAYS}"
if [[ -n "$USER_ID" ]]; then
  snapshot_path="${snapshot_path}&user_id=${USER_ID}"
fi

snapshot_raw="$(request_code "$snapshot_path")"
snapshot_code="$(extract_code "$snapshot_raw")"
snapshot_body="$(extract_body "$snapshot_raw")"

[[ "$snapshot_code" == "200" ]] || fail "/self/reality-check-snapshot returned ${snapshot_code:-unknown}"

SNAPSHOT_JSON="$snapshot_body" \
HEALTH_CODE="$health_code" \
LIVEZ_CODE="$livez_code" \
READYZ_CODE="$readyz_code" \
WARN_AS_FAIL="$WARN_AS_FAIL" \
PRINT_JSON="$PRINT_JSON" \
python3 - <<'PY'
import json
import os
import sys

try:
    snapshot = json.loads(os.environ["SNAPSHOT_JSON"])
except Exception as exc:
    print(f"[reality-check] FAIL: invalid JSON from snapshot endpoint: {exc}", file=sys.stderr)
    sys.exit(1)

dimensions = snapshot.get("dimensions") or {}
summary = {
    "status": snapshot.get("status"),
    "overall": snapshot.get("overall"),
    "period_hours": snapshot.get("period_hours"),
    "period_days": snapshot.get("period_days"),
    "health_http": int(os.environ["HEALTH_CODE"]),
    "livez_http": int(os.environ["LIVEZ_CODE"]),
    "readyz_http": int(os.environ["READYZ_CODE"]),
    "dimension_statuses": {
        key: (value or {}).get("status")
        for key, value in dimensions.items()
    },
    "metric_statuses": {
        key: {
            metric_name: (metric_payload or {}).get("status")
            for metric_name, metric_payload in ((value or {}).get("metrics") or {}).items()
        }
        for key, value in dimensions.items()
    },
}

if os.environ.get("PRINT_JSON") == "1":
    print(json.dumps(summary, indent=2, sort_keys=True))
else:
    print("Reality check summary")
    print(f"status: {summary['status']}")
    print(f"overall: {summary['overall']}")
    print(f"period_hours: {summary['period_hours']}")
    print(f"period_days: {summary['period_days']}")
    print(f"health_http: {summary['health_http']}")
    print(f"livez_http: {summary['livez_http']}")
    print(f"readyz_http: {summary['readyz_http']}")
    for key in sorted(summary["dimension_statuses"]):
        print(f"dimension.{key}: {summary['dimension_statuses'][key]}")

if snapshot.get("status") != "success":
    sys.exit(1)

overall = snapshot.get("overall")
if overall == "fail":
    sys.exit(1)
if overall == "warn" and os.environ.get("WARN_AS_FAIL") == "1":
    sys.exit(1)
sys.exit(0)
PY

info "PASS: reality check completed"
