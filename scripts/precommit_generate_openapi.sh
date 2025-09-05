#!/usr/bin/env bash
set -euo pipefail

# Generate OpenAPI and add it to the index if changed
ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
OUTPUT="${ROOT_DIR}/app/static/openapi.json"

# Ensure poetry is available and deps installed
if ! command -v poetry >/dev/null 2>&1; then
  echo "poetry not found. Please install poetry to run this hook." >&2
  exit 1
fi

# Run generator
poetry run generate-openapi --out "${OUTPUT}"

# If file changed, add it to git index so commit includes it
if ! git diff --quiet -- "${OUTPUT}"; then
  git add "${OUTPUT}"
  echo "Updated ${OUTPUT} and staged changes."
else
  echo "OpenAPI is up-to-date."
fi
