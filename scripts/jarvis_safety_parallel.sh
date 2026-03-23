#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_CMD="ssh jarvis-nas"
DOCKER_CMD="/usr/local/bin/docker"
CONTAINER="jarvis-ingestion"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

GUARDRAILS_OUT="$TMP_DIR/guardrails.out"
SANDBOX_OUT="$TMP_DIR/sandbox.out"

run_guardrails_probe() {
  $SSH_CMD "$DOCKER_CMD exec $CONTAINER python -c \"import json; from app.tool_modules.guardrails_tools import check_guardrails; allow=check_guardrails(action_type='tool_call', tool_name='system_pulse', context={'confidence':0.95}, session_id='onecmd-safety-probe'); block=check_guardrails(action_type='tool_call', tool_name='request_override', context={'confidence':0.95}, session_id='onecmd-safety-probe'); passed=bool(allow.get('allowed') is True and block.get('allowed') is False and len(block.get('blocking_reasons') or []) > 0); out={'probe':'guardrails','status':'PASS' if passed else 'FAIL','allow_allowed':allow.get('allowed'),'block_allowed':block.get('allowed'),'block_reasons':block.get('blocking_reasons')}; print('__PROBE_JSON__'+json.dumps(out, default=str))\"" >"$GUARDRAILS_OUT" 2>&1
}

run_sandbox_probe() {
  $SSH_CMD "$DOCKER_CMD exec $CONTAINER python -c \"import json; from app.live_config import get_config,set_config; from app.sandbox import get_sandbox_service; old=bool(get_config('sandbox_runtime_enabled', False)); out={'probe':'sandbox','initial_enabled':old}; set_config('sandbox_runtime_enabled', True, updated_by='onecmd_safety_probe'); sid=None
try:
    s=get_sandbox_service()
    sess=s.create_session(purpose='onecmd_safety_probe')
    sid=sess['session_id']
    ok=s.execute_python(session_id=sid, code='print(2+2)')
    esc=s.execute_python(session_id=sid, code='from pathlib import Path\\nPath(\\'../escape.txt\\').write_text(\\'x\\')\\nprint(\\'done\\')')
    escape_blocked=bool(esc.get('status')=='error' and 'outside sandbox workspace' in (esc.get('stderr') or ''))
    passed=bool(ok.get('status')=='ok' and escape_blocked)
    out.update({'status':'PASS' if passed else 'FAIL','exec_ok_status':ok.get('status'),'escape_status':esc.get('status'),'escape_blocked':escape_blocked})
finally:
    if sid:
        try:
            get_sandbox_service().cleanup_session(sid)
        except Exception:
            pass
    set_config('sandbox_runtime_enabled', old, updated_by='onecmd_safety_probe_restore')
    out['restored_enabled']=bool(get_config('sandbox_runtime_enabled', False))
print('__PROBE_JSON__'+json.dumps(out, default=str))\"" >"$SANDBOX_OUT" 2>&1
}

run_guardrails_probe &
PID_G=$!
run_sandbox_probe &
PID_S=$!

wait "$PID_G"
CODE_G=$?
wait "$PID_S"
CODE_S=$?

extract_probe_json() {
  local file="$1"
  grep '^__PROBE_JSON__' "$file" | tail -n1 | sed 's/^__PROBE_JSON__//'
}

G_JSON="$(extract_probe_json "$GUARDRAILS_OUT" || true)"
S_JSON="$(extract_probe_json "$SANDBOX_OUT" || true)"

python3 - <<'PY' "$CODE_G" "$CODE_S" "$G_JSON" "$S_JSON"
import json
import sys

code_g = int(sys.argv[1])
code_s = int(sys.argv[2])
g_json = sys.argv[3]
s_json = sys.argv[4]

def safe_load(raw):
    if not raw:
        return {"status": "FAIL", "error": "missing probe json"}
    try:
        return json.loads(raw)
    except Exception as exc:
        return {"status": "FAIL", "error": f"invalid probe json: {exc}"}

g = safe_load(g_json)
s = safe_load(s_json)

print("Cross-Task Safety Probe")
print("======================")
print(f"guardrails: {g.get('status', 'FAIL')} (exit={code_g})")
print(f"sandbox:    {s.get('status', 'FAIL')} (exit={code_s})")

overall_pass = (
    code_g == 0
    and code_s == 0
    and g.get("status") == "PASS"
    and s.get("status") == "PASS"
    and s.get("restored_enabled") == s.get("initial_enabled")
)

if overall_pass:
    print("overall: PASS")
    sys.exit(0)

print("overall: FAIL")
if g.get("status") != "PASS":
    print(f"guardrails_detail: {json.dumps(g, ensure_ascii=True)}")
if s.get("status") != "PASS" or s.get("restored_enabled") != s.get("initial_enabled"):
    print(f"sandbox_detail: {json.dumps(s, ensure_ascii=True)}")
sys.exit(1)
PY
