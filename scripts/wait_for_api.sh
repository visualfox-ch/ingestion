#!/bin/bash
# Wait for localhost:8000 to be reachable (max 60s)
set -e
for i in {1..60}; do
  if curl -s http://192.168.1.103:18000/ > /dev/null; then
    echo "API is up after $i seconds."
    exit 0
  fi
  sleep 1
done
echo "API did not become available after 60 seconds!"
exit 1
