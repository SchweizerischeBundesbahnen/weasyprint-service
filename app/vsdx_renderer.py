"""
Visio drawings through weasyvsdx.

weasyvsdx lets WeasyPrint draw VSDX and VSD natively through the tools of libvisio, so a drawing stays
vector in the PDF. It needs vsd2xhtml of libvisio-tools; without it Visio images are left out of the PDF.
"""

from __future__ import annotations

import importlib.metadata
import logging

import weasyvsdx

logger = logging.getLogger(__name__)

# The libvisio release of the last install, read once: vsd2xhtml --version runs a process
_LIBVISIO: dict[str, str | None] = {}


def configure_vsdx() -> bool:
    """
    Install weasyvsdx, when vsd2xhtml is on the PATH.

    weasyvsdx patches WeasyPrint for the whole process. It draws the text of a drawing with the
    foreignObject of weasysvg, so weasysvg must be installed first (configure_svg_renderer).
    Without vsd2xhtml nothing is patched.

    Returns:
        Whether weasyvsdx is installed.
    """
    converter = weasyvsdx.find_converter()
    if converter is None:
        logger.warning("vsd2xhtml not found: install libvisio-tools, Visio images are left out of the PDF")
        return False
    weasyvsdx.install(converter=converter)
    _LIBVISIO["version"] = weasyvsdx.libvisio_version(converter)
    return True


def get_weasyvsdx_version() -> str:
    """Return the installed weasyvsdx version."""
    return importlib.metadata.version("weasyvsdx")


def get_libvisio_version() -> str | None:
    """Return the libvisio version weasyvsdx runs, or None while it is not installed."""
    return _LIBVISIO.get("version")
