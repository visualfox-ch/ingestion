#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://192.168.1.103:18000}"
ENDPOINT="${API_URL%/}/agent"

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

namespace_resp="$(curl -sS --max-time 60 "$ENDPOINT" \
  -H 'Content-Type: application/json' \
  -d '{"query":"contract smoke namespace","namespace":"work_projektil","max_tokens":64,"stream":false,"source":"api"}')"

python3 - "$namespace_resp" <<'PY' || fail "legacy namespace payload rejected"
import json
import sys
payload = json.loads(sys.argv[1])
if not payload.get("answer") or payload.get("error") is not None:
    raise SystemExit(1)
PY
pass "legacy namespace payload accepted"

scope_resp="$(curl -sS --max-time 60 "$ENDPOINT" \
  -H 'Content-Type: application/json' \
  -d '{"query":"contract smoke scope","scope":{"org":"personal","visibility":"private"},"max_tokens":64,"stream":false,"source":"api"}')"

python3 - "$scope_resp" <<'PY' || fail "scope payload rejected"
import json
import sys
payload = json.loads(sys.argv[1])
if not payload.get("answer") or payload.get("error") is not None:
    raise SystemExit(1)
PY
pass "scope payload accepted"

http_code="$(curl -sS --max-time 30 -o /tmp/agent_contract_invalid.json -w '%{http_code}' "$ENDPOINT" \
  -H 'Content-Type: application/json' \
  -d '{"query":"contract smoke invalid","namespace":"","stream":false,"source":"api"}')"

[[ "$http_code" == "400" ]] || fail "invalid payload did not return HTTP 400"

grep -q 'namespace or scope is required' /tmp/agent_contract_invalid.json || fail "invalid payload error text changed"
pass "invalid payload rejected with expected message"

printf 'OK: /agent contract checks passed\n'
