#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

CONFIG_PATH="${CONFIG_PATH:-config/server.env}"

if [ -f "${CONFIG_PATH}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${CONFIG_PATH}"
  set +a
fi

HOST="${RS_AGENT_HOST:-0.0.0.0}"
PORT="${RS_AGENT_PORT:-8000}"
LOG_FILE="${RS_AGENT_LOG_FILE:-logs/server/server.log}"

mkdir -p "$(dirname "${LOG_FILE}")"

{
  printf 'Starting random signal agent at http://%s:%s\n' "${HOST}" "${PORT}"
  python server.py --host "${HOST}" --port "${PORT}"
} 2>&1 | tee "${LOG_FILE}"
