#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run the deterministic gdev-agent demo against a local stack.

Usage:
  bash scripts/demo.sh [scripts/demo.py options]
  make demo

Environment:
  BASE_URL          API URL, default http://localhost:8000
  DEMO_LLM_MODE    demo or live, default demo
  PYTHON           Python executable, default .venv/bin/python then python3

Deterministic mode requires the running API to have LLM_MODE=demo in .env:
  printf "\nLLM_MODE=demo\n" >> .env
  docker compose up --build -d
  make demo

Use DEMO_LLM_MODE=live only with LLM_MODE=live, ANTHROPIC_API_KEY, and a small
tenant budget cap configured on the running API.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${BASE_URL:-http://localhost:8000}"
DEMO_LLM_MODE="${DEMO_LLM_MODE:-demo}"
PYTHON_BIN="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

if [[ "$DEMO_LLM_MODE" == "demo" ]]; then
  if [[ ! -f .env ]] || ! grep -Eq '^LLM_MODE=demo([[:space:]#]|$)' .env; then
    echo "ERROR: deterministic demo requires LLM_MODE=demo in .env." >&2
    echo 'Run: printf "\nLLM_MODE=demo\n" >> .env && docker compose up --build -d' >&2
    exit 2
  fi
fi

exec "$PYTHON_BIN" scripts/demo.py --url "$BASE_URL" --llm-mode "$DEMO_LLM_MODE" "$@"
