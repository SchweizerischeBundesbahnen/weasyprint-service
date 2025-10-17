#!/usr/bin/env bash
set -euo pipefail

# Start the app locally and save app/static/openapi.json
# - Starts FastAPI on configurable port via python from local virtualenv only
# - Waits until OpenAPI endpoint is up
# - Downloads and pretty-prints directly to docs/openapi.json

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
OUTPUT="${ROOT_DIR}/docs/openapi.json"
PORT="${OPENAPI_PORT:-9980}"
URL="http://localhost:${PORT}/static/openapi.json"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Error: required command '$1' not found." >&2; exit 1; }; }

need_cmd curl
need_cmd lsof

wait_for_url() {
  local url="$1"; local timeout="${2:-90}"; local start now
  start=$(date +%s)
  echo "Waiting for ${url} to become available (timeout=${timeout}s)..."
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "Endpoint is available: $url"
      return 0
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$timeout" ]; then
      echo "Error: Timeout waiting for $url" >&2
      return 1
    fi
    sleep 2
  done
}

APP_PID=""
LOG_DIR_LOCAL=""
cleanup() {
  if [ -n "${APP_PID}" ]; then
    echo "Stopping local FastAPI app (pid=${APP_PID})..."
    kill "${APP_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${LOG_DIR_LOCAL}" ] && [ -d "${LOG_DIR_LOCAL}" ]; then
    rm -rf "${LOG_DIR_LOCAL}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

LOG_DIR_LOCAL="$(mktemp -d 2>/dev/null || mktemp -d -t weasyprint-logs)"
export LOG_DIR="$LOG_DIR_LOCAL"

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv not found. Please install uv: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

# Ensure the selected port is free before starting
if lsof -ti :"${PORT}" >/dev/null 2>&1; then
  echo "Error: Port ${PORT} is already in use. Set OPENAPI_PORT to a free port and retry." >&2
  exit 1
fi

echo "Starting local FastAPI app via uv on port ${PORT}..."
(cd "$ROOT_DIR" && LOG_DIR="$LOG_DIR_LOCAL" uv run python -m app.weasyprint_service_application --port "${PORT}") >/dev/null 2>&1 &

wait_for_url "$URL" 60

APP_PID=$(lsof -ti :"${PORT}" || true)

mkdir -p "$(dirname "$OUTPUT")"

# Stream directly into OUTPUT, pretty-print with jq if available
if command -v jq >/dev/null 2>&1; then
  if curl -fsS "$URL" | jq '.' > "$OUTPUT"; then
    echo "Saved ${OUTPUT} from ${URL}."
  else
    echo "Error: Failed to download or format OpenAPI from ${URL}" >&2
    exit 1
  fi
else
  if curl -fsS "$URL" > "$OUTPUT"; then
    echo "Saved ${OUTPUT} from ${URL}."
  else
    echo "Error: Failed to download OpenAPI from ${URL}" >&2
    exit 1
  fi
fi
