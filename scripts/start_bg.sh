#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/logs/bot.pid"
OUT_FILE="$PROJECT_ROOT/logs/stdout.log"

mkdir -p "$PROJECT_ROOT/logs"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Bot is already running, PID=$old_pid"
    exit 0
  fi
fi

cd "$PROJECT_ROOT"
nohup "$PROJECT_ROOT/scripts/start_uv.sh" >> "$OUT_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" > "$PID_FILE"

echo "Started in background, PID=$new_pid"
echo "PID file: $PID_FILE"
echo "Output log: $OUT_FILE"