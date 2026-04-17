#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SIGNAL="TERM"
if [[ "${1:-}" == "-9" || "${1:-}" == "--force" ]]; then
  SIGNAL="KILL"
fi

PATTERNS=(
  "$PROJECT_ROOT/.venv/bin/python3 ./main.py"
  "uv run ./main.py"
  "$PROJECT_ROOT/main.py"
)

PIDS=()
for pattern in "${PATTERNS[@]}"; do
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && PIDS+=("$pid")
  done < <(pgrep -f "$pattern" || true)
done

if [[ ${#PIDS[@]} -eq 0 ]]; then
  echo "No bot process found for $PROJECT_ROOT"
  exit 0
fi

# 去重
mapfile -t UNIQUE_PIDS < <(printf "%s\n" "${PIDS[@]}" | awk '!seen[$0]++')

echo "Killing PIDs (${SIGNAL}): ${UNIQUE_PIDS[*]}"
kill -s "$SIGNAL" "${UNIQUE_PIDS[@]}"
echo "Done"