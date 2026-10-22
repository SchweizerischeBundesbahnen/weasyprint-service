"""
Selection of the SVG renderer.

SVG_RENDERER picks who draws the SVG of a document. ``chromium`` (default) rasterizes it to PNG
through the browser. ``weasysvg`` lets WeasyPrint draw it natively, so it stays vector in the PDF,
and the service starts no browser.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os

import weasysvg

CHROMIUM = "chromium"
WEASYSVG = "weasysvg"
SVG_RENDERERS = (CHROMIUM, WEASYSVG)
DEFAULT_SVG_RENDERER = CHROMIUM

logger = logging.getLogger(__name__)


def get_svg_renderer() -> str:
    """
    Read the SVG renderer from the SVG_RENDERER variable.

    Returns:
        ``chromium`` or ``weasysvg``. The value is case-insensitive and may carry whitespace.
        An unset, empty or unknown value falls back to ``chromium``.
    """
    value = os.environ.get("SVG_RENDERER", DEFAULT_SVG_RENDERER).strip().lower()
    if not value:
        return DEFAULT_SVG_RENDERER
    if value not in SVG_RENDERERS:
        logger.warning("Invalid SVG_RENDERER value '%s', using default: %s", value, DEFAULT_SVG_RENDERER)
        return DEFAULT_SVG_RENDERER
    return value


def configure_svg_renderer() -> str:
    """
    Select the SVG renderer and prepare WeasyPrint for it.

    weasysvg patches WeasyPrint for the whole process, so it is installed only when it is selected.

    Returns:
        The selected renderer.
    """
    renderer = get_svg_renderer()
    if renderer == WEASYSVG:
        weasysvg.install()
    return renderer


def get_weasysvg_version() -> str:
    """Return the installed weasysvg version."""
    return importlib.metadata.version("weasysvg")
