#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASKS_FILE="$ROOT_DIR/TASKS.md"
ROUTING_FILE="$ROOT_DIR/docs/agents/AGENT_ROUTING.md"

fail=0

if [ ! -f "$TASKS_FILE" ]; then
  echo "ERROR: TASKS.md not found"
  exit 1
fi

# Check TASKS.md size (rough guardrail)
LINES=$(wc -l < "$TASKS_FILE")
if [ "$LINES" -gt 400 ]; then
  echo "WARN: TASKS.md is large (${LINES} lines). Consider archiving old sections."
fi

# Check for required fields in TASKS header
if ! grep -n "Routing Rules" "$TASKS_FILE" >/dev/null; then
  echo "WARN: TASKS.md missing Routing Rules link"
fi

# Check for Handoff blocks missing fields
missing_handoff=$(grep -c "Handoff to Copilot:" "$TASKS_FILE" 2>/dev/null || true)
if [ "$missing_handoff" -gt 0 ]; then
  if ! python3 - "$TASKS_FILE" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
required = [
    "Gate:",
    "Owner:",
    "Status:",
    "Next Action:",
    "Evidence (signal):",
    "Verify (NAS):",
    "Files:",
]

parts = re.split(r"^Handoff to Copilot:\s*$", text, flags=re.MULTILINE)
if len(parts) <= 1:
    sys.exit(0)

for block in parts[1:]:
    window = block.split("\n\n", 1)[0]
    if not all(key in window for key in required):
        sys.exit(1)

sys.exit(0)
PY
  then
    echo "ERROR: Handoff block missing required fields (Gate/Owner/Status/Next Action/Evidence (signal)/Verify (NAS)/Files)"
    fail=1
  fi
fi

# Check for Gate tag in task templates
if [ -f "$ROOT_DIR/tasks/TEMPLATE.md" ]; then
  if ! grep -n "Gate:" "$ROOT_DIR/tasks/TEMPLATE.md" >/dev/null; then
    echo "ERROR: tasks/TEMPLATE.md missing Gate field"
    fail=1
  fi
  if ! grep -n "Verify (NAS):" "$ROOT_DIR/tasks/TEMPLATE.md" >/dev/null; then
    echo "ERROR: tasks/TEMPLATE.md missing Verify (NAS) field"
    fail=1
  fi
fi

# Check routing file exists
if [ ! -f "$ROUTING_FILE" ]; then
  echo "ERROR: docs/agents/AGENT_ROUTING.md missing"
  fail=1
fi

# Check mandatory Subagent & Docs evidence fields for task files that opt into the section
if [ -f "$ROOT_DIR/scripts/lint_task_subagent_evidence.py" ]; then
  if ! python3 "$ROOT_DIR/scripts/lint_task_subagent_evidence.py"; then
    fail=1
  fi
fi

# Check task files use standard status values
VALID_STATI=("BACKLOG" "READY" "IN_PROGRESS" "REVIEW" "DONE" "BLOCKED")
NON_STANDARD=$(find "$ROOT_DIR/tasks/" -name "*.md" -type f -print0 2>/dev/null | \
  xargs -0 grep -hE "^-?[[:space:]]*Status:[[:space:]]*[A-Za-z_]+$" 2>/dev/null | \
  grep -v "Status: BACKLOG" | \
  grep -v "Status: READY" | \
  grep -v "Status: IN_PROGRESS" | \
  grep -v "Status: BLOCKED" | \
  grep -v "Status: REVIEW" | \
  grep -v "Status: DONE" || true)

if [ -n "$NON_STANDARD" ]; then
  echo "ERROR: Non-standard status values found in tasks/:"
  echo "$NON_STANDARD"
  echo "Allowed: ${VALID_STATI[*]}"
  echo "Run: bash scripts/normalize-task-status.sh"
  fail=1
fi

# Flag review report (warn-only)
if [ -f "$ROOT_DIR/scripts/flag-review-report.py" ]; then
  echo "INFO: Updating Flag Review section (warn-only)"
  python3 "$ROOT_DIR/scripts/flag-review-report.py" || true
fi

if [ "$fail" -eq 0 ]; then
  echo "OK: board-lint checks passed"
fi

exit "$fail"
