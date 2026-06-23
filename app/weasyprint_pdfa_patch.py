"""Work around a WeasyPrint 69.0 PDF/A regression that silently drops CSS gradients.

Background
----------
WeasyPrint 69.0 reworked PDF colour management (output intents / ICC profiles —
Kozea/WeasyPrint #2631, #2778, #2785, #2788). For a PDF/A document the colours
go through the output-intent sRGB ICC profile, and WeasyPrint writes the gradient
*shading* colour space — and the transparency *group* colour space — as the bare
resource name ``/srgb`` instead of a direct colour-space object.

Common PDF rasterisers (pdfium / MuPDF, Apache PDFBox) do not resolve a named
colour space for a shading (``unknown colorspace: srgb``), so every CSS
``linear-gradient`` background disappears from PDF/A output. WeasyPrint 68.1 used
``/DeviceRGB`` directly and did not have this problem.

Fix
---
Rewrite those two colour-space entries as a direct ``[/ICCBased <ref>]`` array,
which every renderer resolves, while keeping the document PDF/A-conformant (same
ICC profile, just referenced directly instead of by name).

This is a temporary shim. ``apply_pdfa_colorspace_patch`` is idempotent and, if a
future WeasyPrint no longer exposes the patched internals, degrades to a no-op
without ever breaking PDF generation. Remove it once fixed upstream.
"""

from __future__ import annotations

import logging
from typing import Any

import pydyf  # type: ignore
from weasyprint.pdf import stream as weasyprint_stream  # type: ignore

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_pdfa_iccbased_colorspace_patch"


def _color_space_value(color_profiles: Any, name: str) -> Any:
    """Return a renderer-safe colour-space value for ``name``.

    For an output-intent ICC profile (e.g. ``srgb``) return a direct
    ``[/ICCBased <ref>]`` array; otherwise keep the bare ``/name`` (device colour
    spaces such as ``/DeviceRGB`` are resolved by every reader).
    """
    profile = color_profiles.get(name) if color_profiles else None
    if profile is not None and getattr(profile, "pdf_reference", None) is not None:
        return pydyf.Array(("/ICCBased", profile.pdf_reference))
    return f"/{name}"


def apply_pdfa_colorspace_patch() -> bool:
    """Monkey-patch WeasyPrint so PDF/A gradients use a direct ICCBased colour space.

    Returns ``True`` when the patch is applied, ``False`` when it was already
    applied or the WeasyPrint internals could not be located.
    """
    stream_cls = getattr(weasyprint_stream, "Stream", None)
    if stream_cls is None:
        logger.warning("WeasyPrint Stream class not found; PDF/A gradient patch skipped")
        return False
    if getattr(stream_cls, _PATCH_FLAG, False):
        return False

    original_add_shading = stream_cls.add_shading
    original_add_group = stream_cls.add_group

    def add_shading(self: Any, shading_type: Any, domain: Any, coords: Any, extend: Any, function: Any, color_space: str | None = None) -> Any:
        shading = original_add_shading(self, shading_type, domain, coords, extend, function, color_space)
        try:
            name = color_space or self._default_color_space
            shading["ColorSpace"] = _color_space_value(self._color_profiles, name)
        except Exception:
            logger.warning("PDF/A shading colour-space patch skipped for one shading", exc_info=True)
        return shading

    def add_group(self: Any, x: Any, y: Any, width: Any, height: Any) -> Any:
        group = original_add_group(self, x, y, width, height)
        try:
            group.extra["Group"]["CS"] = _color_space_value(self._color_profiles, self._default_color_space)
        except Exception:
            logger.warning("PDF/A group colour-space patch skipped for one group", exc_info=True)
        return group

    stream_cls.add_shading = add_shading
    stream_cls.add_group = add_group
    setattr(stream_cls, _PATCH_FLAG, True)
    logger.info("Applied WeasyPrint PDF/A gradient colour-space patch (named /srgb -> direct ICCBased)")
    return True
