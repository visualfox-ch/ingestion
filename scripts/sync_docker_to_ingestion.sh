#!/bin/bash

set -euo pipefail

DOCKER_ROOT="${DOCKER_ROOT:-/Volumes/BRAIN/system/docker}"
INGESTION_ROOT="${INGESTION_ROOT:-/Volumes/BRAIN/system/ingestion}"

if [ ! -d "$INGESTION_ROOT" ]; then
  echo "❌ Ingestion repo not found at $INGESTION_ROOT"
  exit 2
fi

if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
else
  DRY_RUN=0
fi

if [ -d "$DOCKER_ROOT/.git" ]; then
  changed_files="$(
    git -C "$DOCKER_ROOT" diff --name-only
    git -C "$DOCKER_ROOT" diff --name-only --cached
  )"
else
  if [ -z "${SYNC_FILES:-}" ]; then
    echo "❌ Docker repo git metadata missing. Set SYNC_FILES to a space-separated list of files."
    exit 2
  fi
  changed_files="$(printf '%s\n' $SYNC_FILES)"
fi

deployable_changes="$(printf '%s\n' "$changed_files" | grep -E '^(app|migrations|scripts)/|^Dockerfile$|^requirements.txt$|^pyproject.toml$' | sort -u || true)"

if [ -z "$deployable_changes" ]; then
  echo "✅ No deployable changes to sync."
  exit 0
fi

echo "🔄 Syncing deployable changes to ingestion repo..."
while IFS= read -r relpath; do
  [ -z "$relpath" ] && continue
  src="$DOCKER_ROOT/$relpath"
  dst="$INGESTION_ROOT/$relpath"

  if [ ! -f "$src" ]; then
    echo "⚠️  Source missing, skipping: $relpath"
    continue
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY RUN: would sync $relpath"
    continue
  fi

  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
  echo "✅ Synced: $relpath"
done <<< "$deployable_changes"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "ℹ️  Dry run complete. Re-run without --dry-run to apply."
fi
