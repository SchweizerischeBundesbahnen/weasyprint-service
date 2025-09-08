#!/usr/bin/env bash
set -euo pipefail

# Generate and stage an up-to-date OpenAPI spec without using Python directly.
# Strategy:
#  - If OPENAPI_SOURCE_URL is provided, fetch from it.
#  - Otherwise, start the FastAPI app locally (via poetry or python), wait until the OpenAPI endpoint responds, fetch it, and then stop the app.
#  - Finally, stage the updated app/static/openapi.json if it changed.

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
OUTPUT="${ROOT_DIR}/app/static/openapi.json"
DEFAULT_URL="http://localhost:9980/static/openapi.json"
URL="${OPENAPI_SOURCE_URL:-$DEFAULT_URL}"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Error: required command '$1' not found." >&2; exit 1; }; }

# Ensure curl is available
need_cmd curl


# Helper to wait for URL to be ready (HTTP 200)
wait_for_url() {
  local url="$1"; local timeout="${2:-90}"; local start ts now
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

# If URL is default localhost, try to start the FastAPI app directly with uvicorn via the project's entry script
APP_PID=""
LOG_DIR_LOCAL=""
cleanup() {
  if [ -n "${APP_PID}" ]; then
    echo "Stopping local FastAPI app (pid=${APP_PID})..."
    kill "${APP_PID}" >/dev/null 2>&1 || true
  fi
  # Optional: cleanup temporary logs directory if empty
  if [ -n "${LOG_DIR_LOCAL}" ] && [ -d "${LOG_DIR_LOCAL}" ]; then
    rmdir "${LOG_DIR_LOCAL}" >/dev/null 2>&1 || true
    rmdir "$(dirname "${LOG_DIR_LOCAL}")" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [ "$URL" = "$DEFAULT_URL" ]; then
  # Ensure a writable LOG_DIR for local run to avoid permission issues with /opt/weasyprint/logs
  LOG_DIR_LOCAL="${ROOT_DIR}/.logs"
  mkdir -p "$LOG_DIR_LOCAL"
  export LOG_DIR="$LOG_DIR_LOCAL"
  if command -v poetry >/dev/null 2>&1; then
    echo "Starting local FastAPI app via poetry on port 9980 (LOG_DIR=$LOG_DIR_LOCAL)..."
    (cd "$ROOT_DIR" && LOG_DIR="$LOG_DIR_LOCAL" poetry run python -m app.weasyprint_service_application --port 9980) >/dev/null 2>&1 &
    APP_PID=$!
  elif command -v python >/dev/null 2>&1; then
    echo "Starting local FastAPI app via python on port 9980 (LOG_DIR=$LOG_DIR_LOCAL)..."
    (cd "$ROOT_DIR" && LOG_DIR="$LOG_DIR_LOCAL" python -m app.weasyprint_service_application --port 9980) >/dev/null 2>&1 &
    APP_PID=$!
  else
    echo "Note: Neither poetry nor python is available. Assuming the service is already running at $URL."
  fi
fi

# Wait for the endpoint to be ready, then fetch
wait_for_url "$URL" 120
TMP_FILE="${OUTPUT}.tmp"
mkdir -p "$(dirname "$OUTPUT")"

# Fetch the OpenAPI JSON
if curl -fsS "$URL" -o "$TMP_FILE"; then
  # If jq is available, pretty-print and normalize
  if command -v jq >/dev/null 2>&1; then
    # Deterministic formatting: sort all object keys recursively (-S) and pretty-print
    jq -S '.' "$TMP_FILE" > "${TMP_FILE}.fmt" && mv "${TMP_FILE}.fmt" "$TMP_FILE"
  else
    echo "Warning: jq not found. OpenAPI JSON will not be sorted; diffs may be noisy." >&2
  fi
  # Only replace if changed
  if [ ! -f "$OUTPUT" ] || ! cmp -s "$TMP_FILE" "$OUTPUT"; then
    mv "$TMP_FILE" "$OUTPUT"
    echo "Updated ${OUTPUT} from ${URL}."
  else
    rm -f "$TMP_FILE"
    echo "No changes in OpenAPI specification."
  fi
else
  echo "Error: Failed to download OpenAPI from ${URL}" >&2
  # Cleanup and exit with error
  rm -f "$TMP_FILE" || true
  exit 1
fi

# If we started a local app process, stop it
if [ -n "${APP_PID}" ]; then
  echo "Stopping local FastAPI app (pid=${APP_PID})..."
  kill "$APP_PID" >/dev/null 2>&1 || true
fi

# Stage changes if any
if ! git diff --quiet -- "$OUTPUT"; then
  git add "$OUTPUT"
  echo "Staged changes in ${OUTPUT}."
else
  echo "OpenAPI is up-to-date (no changes to stage)."
fi
