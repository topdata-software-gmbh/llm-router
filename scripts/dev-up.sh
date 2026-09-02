#!/usr/bin/env bash
#
# Start local development server with hot-reload (uv, no Docker)
# 09/2026 created
#

set -e

usage() {
  cat <<EOF
Usage: ./scripts/dev-up.sh [uvicorn options...]

Starts the local development server with --reload. Applies Alembic migrations
first (the SQLite schema lives at llm_router.db). The port defaults to \$PORT
from .env, falling back to 8202 (see src/llm_router/config.py).

Options:
  -h, --help            Show this help and exit.
  --port PORT           Run on a custom port (overrides \$PORT / default).

Examples:
  ./scripts/dev-up.sh
      Start on the default port (http://localhost:8202).

  PORT=9000 ./scripts/dev-up.sh
      Start on port 9000 via the PORT environment variable.

  ./scripts/dev-up.sh --port 9000
      Start on port 9000 (forwarded to uvicorn).

  ./scripts/dev-up.sh --host 0.0.0.0 --port 9000
      Bind all interfaces on port 9000 (forwarded to uvicorn).

Any extra arguments are passed through to uvicorn (see 'uv run uvicorn --help').
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
  esac
done

PWD=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
PROJECT_ROOT=$(realpath $PWD/..)

cd $PROJECT_ROOT

PORT="${PORT:-}"
if [ -z "$PORT" ] && [ -f .env ]; then
  PORT=$(grep -E '^PORT=' .env | tail -n1 | cut -d= -f2-)
fi
PORT="${PORT:-8202}"

echo "---- Starting local development server ----"
echo "Applying Alembic migrations..."
uv run python -m alembic upgrade head
echo "API will be available at http://localhost:${PORT}"
echo ""

exec uv run python -m uvicorn llm_router.main:app --reload --host 127.0.0.1 --port "$PORT" "$@"
