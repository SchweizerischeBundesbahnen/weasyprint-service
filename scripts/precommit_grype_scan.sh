#!/usr/bin/env bash
set -euo pipefail

# Run grype vulnerability scan on Docker image
# - Builds the Docker image if needed
# - Scans the image with grype
# - Fails if HIGH or CRITICAL vulnerabilities are found

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
IMAGE_NAME="weasyprint-service:grype-scan"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Error: required command '$1' not found. Install grype from https://github.com/anchore/grype" >&2; exit 1; }; }

need_cmd docker
need_cmd grype

echo "Building Docker image for vulnerability scanning..."
if docker build \
    --build-arg APP_IMAGE_VERSION=0.0.0-scan \
    --file "${ROOT_DIR}/Dockerfile" \
    --tag "${IMAGE_NAME}" \
    "${ROOT_DIR}" >/dev/null 2>&1; then
    echo "Docker image built successfully: ${IMAGE_NAME}"
else
    echo "Error: Failed to build Docker image" >&2
    exit 1
fi

echo "Running grype vulnerability scan on ${IMAGE_NAME}..."
echo "=================================================="

# Run grype and capture both output and exit code
GRYPE_OUTPUT=$(mktemp)
GRYPE_EXIT_CODE=0

# Run grype with table output and fail on HIGH/CRITICAL severities
# --fail-on high will exit with code 1 if HIGH or CRITICAL vulnerabilities are found
if grype "${IMAGE_NAME}" --output table --fail-on high > "${GRYPE_OUTPUT}" 2>&1; then
    GRYPE_EXIT_CODE=0
else
    GRYPE_EXIT_CODE=$?
fi

# Show the grype output
cat "${GRYPE_OUTPUT}"

# Clean up
rm -f "${GRYPE_OUTPUT}"

# Handle exit codes
if [ ${GRYPE_EXIT_CODE} -eq 0 ]; then
    echo "=================================================="
    echo "✅ Vulnerability scan passed: No HIGH or CRITICAL vulnerabilities found"
    exit 0
elif [ ${GRYPE_EXIT_CODE} -eq 1 ]; then
    echo "=================================================="
    echo "❌ Vulnerability scan failed: HIGH or CRITICAL vulnerabilities found"
    echo ""
    echo "To fix vulnerabilities:"
    echo "  1. Update base image or dependencies in pyproject.toml/poetry.lock"
    echo "  2. Run 'poetry update' to update Python dependencies"
    echo "  3. Consider using newer base images in Dockerfile"
    echo ""
    echo "To bypass this check temporarily (not recommended):"
    echo "  SKIP=grype git commit ..."
    exit 1
else
    echo "=================================================="
    echo "⚠️  Grype scan encountered an error (exit code: ${GRYPE_EXIT_CODE})"
    exit ${GRYPE_EXIT_CODE}
fi