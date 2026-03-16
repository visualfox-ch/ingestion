#!/bin/bash

set -euo pipefail

ROOT="/volume1/BRAIN/system/ingestion"
LOG_DIR="$ROOT/logs"
TAG="# jarvis-fx-update"
CRON_LINE="15 16 * * * cd $ROOT && /usr/bin/python3 $ROOT/scripts/update_fx_rates.py --output $ROOT/app/static/fx.json >> $LOG_DIR/fx_update.log 2>&1 $TAG"

mkdir -p "$LOG_DIR"

existing="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$existing" | grep -v "$TAG" || true)"
printf '%s\n%s\n' "$filtered" "$CRON_LINE" | crontab -

echo "Installed FX cron:"
echo "$CRON_LINE"
