#!/usr/bin/env bash
set -euo pipefail

# Smart deploy cycle:
# 1) enforce deploy lock check
# 2) capture before metrics
# 3) pre-deploy gate + safe deploy dry-run
# 4) real BuildKit deploy
# 5) capture after metrics
# 6) print + persist compact before/after report

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/lib/ssh.sh
source "$ROOT/scripts/lib/ssh.sh"

if [[ -z "${NAS_HOST:-}" ]]; then
  if [[ -d /volume1/BRAIN/system/docker ]]; then
    NAS_HOST="localhost"
  else
    NAS_HOST="jarvis-nas"
  fi
fi

NAS_DOCKER_ROOT="${NAS_DOCKER_ROOT:-/volume1/BRAIN/system/docker}"
API_BASE="${JARVIS_API_BASE:-http://127.0.0.1:18000}"
HOURS="${REALITY_CHECK_HOURS:-168}"
DAYS="${REALITY_CHECK_DAYS:-7}"
TARGETED_TEST_FILES="${TARGETED_TEST_FILES:-app/services/self_validation_service.py app/routers/self_validation_router.py tests/test_self_validation_service.py}"
DRY_RUN_ONLY=0
PRINT_JSON=0
REASON="T-RI-22 smart deploy cycle"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      REASON="$2"
      shift 2
      ;;
    --hours)
      HOURS="$2"
      shift 2
      ;;
    --days)
      DAYS="$2"
      shift 2
      ;;
    --dry-run-only)
      DRY_RUN_ONLY=1
      shift
      ;;
    --print-json)
      PRINT_JSON=1
      shift
      ;;
    *)
      echo "[smart-cycle] Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

REPORT_DIR="$ROOT/tmp/deploy-reports"
mkdir -p "$REPORT_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"
REPORT_PATH="$REPORT_DIR/smart_deploy_${STAMP}.md"

echo "[smart-cycle] root=$ROOT"
echo "[smart-cycle] nas_host=$NAS_HOST"
echo "[smart-cycle] nas_root=$NAS_DOCKER_ROOT"
echo "[smart-cycle] report=$REPORT_PATH"

echo "[smart-cycle] Step 1/7: deploy lock check"
lock_out="$(run_host_cmd "ps aux | grep -E 'build-ingestion-fast|agent-deploy' | grep -v grep || true")"
if [[ -n "${lock_out//[[:space:]]/}" ]]; then
  echo "[smart-cycle] FAIL: deployment already running" >&2
  printf '%s\n' "$lock_out" >&2
  exit 1
fi

echo "[smart-cycle] Step 2/7: log deploy intent in TASKS.md"
reason_clean="${REASON//\'/}"
run_host_cmd "cd $NAS_DOCKER_ROOT && TS=\$(date '+%Y-%m-%d %H:%M %Z') && printf -- '- [%s] Copilot smart deploy intent: ${reason_clean}\n' \"\$TS\" >> TASKS.md"

echo "[smart-cycle] Step 3/7: capture BEFORE metrics"
before_proactivity="$(run_host_cmd "curl -sS '${API_BASE}/self/proactivity/score?hours=${HOURS}'")"
before_snapshot="$(run_host_cmd "curl -sS '${API_BASE}/self/reality-check-snapshot?hours=${HOURS}&days=${DAYS}'")"

echo "[smart-cycle] Step 4/7: pre-deploy gate"
run_host_cmd "cd $NAS_DOCKER_ROOT && bash ./scripts/jarvis_pre_deploy_gate.sh"

echo "[smart-cycle] Step 5/7: safe deploy dry-run"
run_host_cmd "cd $NAS_DOCKER_ROOT && TARGETED_TEST_FILES='${TARGETED_TEST_FILES}' SAFE_DEPLOY_DRY_RUN=1 ./scripts/jarvis_safe_deploy.sh '${reason_clean}' --dry-run"

if [[ "$DRY_RUN_ONLY" == "1" ]]; then
  echo "[smart-cycle] DRY RUN ONLY: skipping real deploy"
else
  echo "[smart-cycle] Step 6/7: real BuildKit deploy"
  run_host_cmd "cd $NAS_DOCKER_ROOT && bash ./build-ingestion-fast.sh"
fi

echo "[smart-cycle] Step 7/7: capture AFTER metrics"
after_proactivity="$(run_host_cmd "curl -sS '${API_BASE}/self/proactivity/score?hours=${HOURS}'")"
after_snapshot="$(run_host_cmd "curl -sS '${API_BASE}/self/reality-check-snapshot?hours=${HOURS}&days=${DAYS}'")"

BEFORE_PROACTIVITY="$before_proactivity" \
AFTER_PROACTIVITY="$after_proactivity" \
BEFORE_SNAPSHOT="$before_snapshot" \
AFTER_SNAPSHOT="$after_snapshot" \
REPORT_PATH="$REPORT_PATH" \
REASON="$REASON" \
HOURS="$HOURS" \
DAYS="$DAYS" \
PRINT_JSON="$PRINT_JSON" \
python3 - <<'PY'
import json
import os
from datetime import datetime

before_p = json.loads(os.environ["BEFORE_PROACTIVITY"])
after_p = json.loads(os.environ["AFTER_PROACTIVITY"])
before_s = json.loads(os.environ["BEFORE_SNAPSHOT"])
after_s = json.loads(os.environ["AFTER_SNAPSHOT"])

def get_nested(d, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur

before_hint = before_p.get("hint_stats") or {}
after_hint = after_p.get("hint_stats") or {}

before_dim_proactive = get_nested(before_s, "dimensions", "proactive") or {}
after_dim_proactive = get_nested(after_s, "dimensions", "proactive") or {}

summary = {
    "reason": os.environ["REASON"],
    "hours": int(os.environ["HOURS"]),
    "days": int(os.environ["DAYS"]),
    "timestamp": datetime.now().isoformat(),
    "before": {
        "proactivity_score": before_p.get("proactivity_score"),
        "acceptance_rate": before_hint.get("acceptance_rate"),
        "confidence_adjusted_acceptance_rate": before_hint.get("confidence_adjusted_acceptance_rate"),
        "completed_outcomes": before_hint.get("completed_outcomes"),
        "no_feedback_total": before_hint.get("no_feedback_total"),
        "reality_overall": before_s.get("overall"),
        "reality_proactive_status": before_dim_proactive.get("status"),
    },
    "after": {
        "proactivity_score": after_p.get("proactivity_score"),
        "acceptance_rate": after_hint.get("acceptance_rate"),
        "confidence_adjusted_acceptance_rate": after_hint.get("confidence_adjusted_acceptance_rate"),
        "completed_outcomes": after_hint.get("completed_outcomes"),
        "no_feedback_total": after_hint.get("no_feedback_total"),
        "reality_overall": after_s.get("overall"),
        "reality_proactive_status": after_dim_proactive.get("status"),
    },
}

report_lines = [
    "# Smart Deploy Cycle Report",
    "",
    f"- reason: {summary['reason']}",
    f"- timestamp: {summary['timestamp']}",
    f"- window: hours={summary['hours']} days={summary['days']}",
    "",
    "## Before vs After",
    "",
    "| Metric | Before | After |",
    "| --- | --- | --- |",
]

rows = [
    ("proactivity_score", summary["before"]["proactivity_score"], summary["after"]["proactivity_score"]),
    ("acceptance_rate", summary["before"]["acceptance_rate"], summary["after"]["acceptance_rate"]),
    (
        "confidence_adjusted_acceptance_rate",
        summary["before"]["confidence_adjusted_acceptance_rate"],
        summary["after"]["confidence_adjusted_acceptance_rate"],
    ),
    ("completed_outcomes", summary["before"]["completed_outcomes"], summary["after"]["completed_outcomes"]),
    ("no_feedback_total", summary["before"]["no_feedback_total"], summary["after"]["no_feedback_total"]),
    ("reality_overall", summary["before"]["reality_overall"], summary["after"]["reality_overall"]),
    (
        "reality_proactive_status",
        summary["before"]["reality_proactive_status"],
        summary["after"]["reality_proactive_status"],
    ),
]

for name, b, a in rows:
    report_lines.append(f"| {name} | {b} | {a} |")

report_lines += [
    "",
    "## Raw Payloads",
    "",
    "### BEFORE /self/proactivity/score",
    "```json",
    json.dumps(before_p, ensure_ascii=True, indent=2),
    "```",
    "",
    "### AFTER /self/proactivity/score",
    "```json",
    json.dumps(after_p, ensure_ascii=True, indent=2),
    "```",
    "",
    "### BEFORE /self/reality-check-snapshot",
    "```json",
    json.dumps(before_s, ensure_ascii=True, indent=2),
    "```",
    "",
    "### AFTER /self/reality-check-snapshot",
    "```json",
    json.dumps(after_s, ensure_ascii=True, indent=2),
    "```",
]

report_text = "\n".join(report_lines) + "\n"
with open(os.environ["REPORT_PATH"], "w", encoding="utf-8") as f:
    f.write(report_text)

if os.environ.get("PRINT_JSON") == "1":
    print(json.dumps(summary, ensure_ascii=True, indent=2))
else:
    print("Smart deploy cycle summary")
    print(f"reason: {summary['reason']}")
    print(f"hours: {summary['hours']}")
    print(f"days: {summary['days']}")
    print(f"before.proactivity_score: {summary['before']['proactivity_score']}")
    print(f"after.proactivity_score: {summary['after']['proactivity_score']}")
    print(f"before.reality_overall: {summary['before']['reality_overall']}")
    print(f"after.reality_overall: {summary['after']['reality_overall']}")
    print(f"before.reality_proactive_status: {summary['before']['reality_proactive_status']}")
    print(f"after.reality_proactive_status: {summary['after']['reality_proactive_status']}")
print(f"REPORT_PATH={os.environ['REPORT_PATH']}")
PY

echo "[smart-cycle] PASS"
