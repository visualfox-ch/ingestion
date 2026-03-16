#!/bin/bash
# Check for secrets and sensitive keys in code/config before deploy

set -euo pipefail

PATTERNS=(
  'api[_-]?key\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'secret[_-]?key\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'token\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'password\\s*[:=]\\s*["\\x27]?[^\\s"\\x27]{8,}'
  '-----BEGIN[[:space:]]+.*PRIVATE[[:space:]]+KEY-----'
  'client_secret\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'access_token\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'AUTH_TOKEN\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'OPENAI_API_KEY\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'GITHUB_TOKEN\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
  'STRIPE_SECRET_KEY\\s*[:=]\\s*["\\x27]?[A-Za-z0-9_\\-]{16,}'
)

FAIL=0

INCLUDES=(
  --include=*.py
  --include=*.sh
  --include=*.yml
  --include=*.yaml
  --include=*.json
  --include=*.toml
  --include=*.ini
  --include=Dockerfile
  --include=docker-compose.yml
  --include=docker-compose.*.yml
)

for pattern in "${PATTERNS[@]}"; do
  echo "Checking for pattern: $pattern"
  matches=$(grep -r -i -E \
    --exclude-dir=.venv \
    --exclude-dir=.venv-nas \
    --exclude-dir=.git \
    --exclude-dir=__pycache__ \
    --exclude-dir=@eaDir \
    --exclude-dir=node_modules \
    --exclude-dir=.claude \
    --exclude-dir=.continue \
    --exclude-dir=.vscode \
    --exclude-dir=.codex \
    --exclude-dir=logs \
    --exclude-dir=docs \
    --exclude-dir=roadmap_backup_20260209 \
    --exclude-dir=roadmap_backup \
    --exclude-dir=google-cloud-sdk \
    --exclude-dir=monitoring \
    --exclude-dir=tasks \
    --exclude-dir=tests \
    --exclude-dir=tmp \
    --exclude=.env \
    --exclude=.env.* \
    "${INCLUDES[@]}" \
    -e "$pattern" . || true)
  if [ -n "$matches" ]; then
    echo "❌ Secret pattern found: $pattern"
    echo "$matches"
    FAIL=1
  fi
done

if [ "$FAIL" -eq 0 ]; then
  echo "✅ No secrets found."
  exit 0
else
  echo "❌ Secrets detected. Please remove before deploy."
  exit 1
fi
