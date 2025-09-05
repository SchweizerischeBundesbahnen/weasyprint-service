#!/usr/bin/env python3
"""
Generate OpenAPI schema JSON for the FastAPI app and write it to app/static/openapi.json.

This script imports the FastAPI app from app.weasyprint_controller and dumps the
OpenAPI schema to the static path so that it is served at /static/openapi.json.

Usage:
    python scripts/generate_openapi.py [--out <path>]

If --out is not provided, defaults to app/static/openapi.json relative to repo root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.weasyprint_controller import app

# Ensure project root is on sys.path when executing directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "app" / "static" / "openapi.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OpenAPI JSON from FastAPI app")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output file path for openapi.json")
    args = parser.parse_args()

    schema = app.openapi()

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep a stable, pretty deterministic output for diffs
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
