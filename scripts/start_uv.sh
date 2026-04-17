#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

load_dotenv() {
  local env_file="$1"
  local line key value

  while IFS= read -r line || [[ -n "$line" ]]; do
    # 跳过空行和注释行
    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    # 去掉可选 export 前缀
    line="${line#export }"

    # 只处理 KEY=VALUE 形式
    [[ "$line" == *"="* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"

    # 去除 key 前后空白
    key="$(echo "$key" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

    # 非引号值移除行内注释，并去除首尾空白
    if [[ ! "$value" =~ ^[[:space:]]*".*"[[:space:]]*$ && ! "$value" =~ ^[[:space:]]*'.*'[[:space:]]*$ ]]; then
      value="${value%%#*}"
      value="$(echo "$value" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    else
      value="$(echo "$value" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
      # 去掉包裹引号
      if [[ "$value" =~ ^".*"$ || "$value" =~ ^'.*'$ ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi

    export "$key=$value"
  done < "$env_file"
}

if [[ -f "$ENV_FILE" ]]; then
  load_dotenv "$ENV_FILE"
else
  echo "[WARN] .env not found: $ENV_FILE"
fi

cd "$PROJECT_ROOT"
exec uv run ./main.py "$@"