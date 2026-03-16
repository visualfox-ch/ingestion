#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUT_DIR="${JARVIS_RETRIEVAL_EVAL_OUT_DIR:-/brain/system/logs}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_OUT="${OUT_DIR}/retrieval_eval_default_${TS}.json"
EXPANDED_OUT="${OUT_DIR}/retrieval_eval_expanded_${TS}.json"

THRESH_DEFAULT="${JARVIS_RETRIEVAL_EVAL_THRESHOLD_DEFAULT:-0.6}"
THRESH_EXPANDED="${JARVIS_RETRIEVAL_EVAL_THRESHOLD_EXPANDED:-0.9}"

run_eval() {
  local out_path="$1"
  local queries_env="$2"

  if [ -n "$queries_env" ]; then
    ${ROOT_DIR}/jarvis-docker.sh exec ingestion bash -lc "PYTHONPATH=/brain/system/ingestion JARVIS_RETRIEVAL_EVAL_QUERIES=${queries_env} JARVIS_RETRIEVAL_EVAL_PATH='${out_path}' python /brain/system/ingestion/scripts/eval_retrieval.py"
  else
    ${ROOT_DIR}/jarvis-docker.sh exec ingestion bash -lc "PYTHONPATH=/brain/system/ingestion JARVIS_RETRIEVAL_EVAL_PATH='${out_path}' python /brain/system/ingestion/scripts/eval_retrieval.py"
  fi
}

get_hit_rate() {
  local path="$1"
  ${ROOT_DIR}/jarvis-docker.sh exec ingestion bash -lc "EVAL_PATH='${path}' python - <<'PY'
import json
import os
path = os.environ.get('EVAL_PATH') or ''
if not path:
    print(0.0)
    raise SystemExit(0)
try:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception:
    print(0.0)
    raise SystemExit(0)
print(data.get('summary', {}).get('hit_rate', 0.0))
PY"
}

below_threshold() {
  python3 - <<'PY'
import os
hit = float(os.environ["HIT"])
thr = float(os.environ["THR"])
raise SystemExit(0 if hit < thr else 1)
PY
}

EXPANDED_JSON_SHELL="$(python3 - <<'PY'
import json
import shlex
queries = [
    {"query": "context aware decision engine architecture", "expect": ["AI1_CONTEXT_AWARE_DECISION_ENGINE_ARCHITECTURE.md"], "namespace": "work"},
    {"query": "intelligence features pipeline advanced", "expect": ["INTELLIGENCE_FEATURES_PIPELINE_ADVANCED.md"], "namespace": "work"},
    {"query": "work_projektil email inbox", "expect": ["work_projektil/email/inbox/"], "namespace": "work"},
    {"query": "projektil email", "expect": ["work_projektil/email/inbox/"], "namespace": "work"},
    {"query": "context-aware decision engine", "expect": ["AI1_CONTEXT_AWARE_DECISION_ENGINE_ARCHITECTURE.md"], "namespace": "work"},
]
print(shlex.quote(json.dumps(queries)))
PY
)"

echo "[retrieval-eval] default queries -> ${DEFAULT_OUT}"
run_eval "$DEFAULT_OUT" ""

echo "[retrieval-eval] expanded queries -> ${EXPANDED_OUT}"
run_eval "$EXPANDED_OUT" "$EXPANDED_JSON_SHELL"

default_hit="$(get_hit_rate "$DEFAULT_OUT")"
expanded_hit="$(get_hit_rate "$EXPANDED_OUT")"

echo "[retrieval-eval] default hit_rate=${default_hit} (threshold=${THRESH_DEFAULT})"
echo "[retrieval-eval] expanded hit_rate=${expanded_hit} (threshold=${THRESH_EXPANDED})"

alert="false"
if HIT="${default_hit}" THR="${THRESH_DEFAULT}" below_threshold; then
  alert="true"
fi
if HIT="${expanded_hit}" THR="${THRESH_EXPANDED}" below_threshold; then
  alert="true"
fi

if [ "$alert" = "true" ]; then
  ${ROOT_DIR}/jarvis-message.sh "Retrieval eval regression detected. Default hit_rate=${default_hit} (thr=${THRESH_DEFAULT}); Expanded hit_rate=${expanded_hit} (thr=${THRESH_EXPANDED})." --level warning || true
fi
