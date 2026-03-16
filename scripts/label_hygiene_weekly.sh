#!/usr/bin/env bash
set -euo pipefail

# Weekly label hygiene (read-only by default).
# Guarded auto-register requires JARVIS_LABEL_HYGIENE_AUTOREGISTER=true.

LIMIT="${1:-2000}"
APPLY="${2:-false}"

./jarvis-docker.sh exec ingestion python -c "import app.tools as t; print(t.tool_label_hygiene(limit=${LIMIT}, apply=${APPLY}))"
