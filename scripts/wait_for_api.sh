#!/bin/bash
# Wait until the API is both accepting requests and serving the full health endpoint.
set -euo pipefail

BASE_URL="${JARVIS_API_BASE_URL:-http://192.168.1.103:18000}"

for i in {1..60}; do
  if curl -fsS -m 3 "$BASE_URL/readyz" > /dev/null && curl -fsS -m 5 "$BASE_URL/health" > /dev/null; then
    echo "API ready after $i seconds."
    exit 0
  fi
  sleep 1
done

echo "API did not become ready after 60 seconds!"
exit 1
