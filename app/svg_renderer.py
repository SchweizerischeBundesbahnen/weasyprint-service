"""
The SVG renderer.

weasysvg lets WeasyPrint draw the SVG of a document natively, so it stays vector in the PDF.
It is the only renderer: the Chromium renderer of earlier versions is gone. SVG_RENDERER is
read only to warn a deployment which still asks for another renderer.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os

import weasysvg

WEASYSVG = "weasysvg"

logger = logging.getLogger(__name__)


def warn_about_svg_renderer() -> None:
    """Log a warning when SVG_RENDERER asks for a renderer other than weasysvg. It never fails."""
    value = os.environ.get("SVG_RENDERER", "").strip()
    if value and value.lower() != WEASYSVG:
        logger.warning("SVG_RENDERER=%s is no longer supported; weasysvg draws SVG", value)


def configure_svg_renderer() -> str:
    """
    Install weasysvg, which patches WeasyPrint for the whole process.

    Returns:
        The renderer, always ``weasysvg``.
    """
    warn_about_svg_renderer()
    weasysvg.install()
    return WEASYSVG


def get_weasysvg_version() -> str:
    """Return the installed weasysvg version."""
    return importlib.metadata.version("weasysvg")
