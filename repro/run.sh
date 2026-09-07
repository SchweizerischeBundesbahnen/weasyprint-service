#!/usr/bin/env bash
#
# Native repro — runs straight on the host (no weasyprint-service, no Docker).
#
# Runs both reproductions in this directory. See README.md.
#
# Prerequisites:
#   * uv                      (https://docs.astral.sh/uv/)
#   * WeasyPrint system libs  — macOS:  brew install pango
#                                        (pulls glib/gobject, cairo, harfbuzz, …)
#                               Linux:  apt-get install libpango-1.0-0 libpangocairo-1.0-0
#
# Usage:  ./run.sh
#
set -euo pipefail
cd "$(dirname "$0")"

# macOS (Apple Silicon/Intel): let dlopen find Homebrew's libgobject/libpango/libcairo.
if command -v brew >/dev/null 2>&1; then
  export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
fi

echo "== PDF/A gradients =="
for v in 68.1 69.0; do
  uv run --quiet --with "weasyprint==$v" --with pymupdf repro.py
done
# Same broken version, but with the weasyprint-service fix applied:
uv run --quiet --with "weasyprint==69.0" --with pymupdf repro.py --patch

echo
echo "== Running element in a shrink-to-fit box =="
for v in 68.1 69.0; do
  uv run --quiet --with "weasyprint==$v" --with pymupdf repro_running_element.py
done
uv run --quiet --with "weasyprint==69.0" --with pymupdf repro_running_element.py --patch
