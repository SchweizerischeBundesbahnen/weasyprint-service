"""Give the characters of the Unicode Private Use Area an ActualText in a tagged PDF.

Background
----------
Icon fonts such as Font Awesome draw their icons with characters of the Private Use
Area (PUA). The level A of PDF/A-2 and PDF/A-3 requires an ActualText for every such
character (ISO 32000-1:2008, 14.9.4; veraPDF rule 6.2.11.7.3-1), and PDF/UA-2 requires
an ActualText or an Alt. WeasyPrint writes neither for text, so a document with a
single icon fails these variants.

Fix
---
When WeasyPrint writes a tagged PDF, wrap each text box which holds a PUA character in
a ``/Span`` marked-content sequence with an ``ActualText``. The ActualText is the text
of the box without its PUA characters. A box which holds nothing else, an icon, takes
the ``aria-label`` of its element in place of the icon, or nothing, and keeps its
spaces. The glyphs are drawn as before, so the
page does not change; a reader or an extraction reads the ActualText instead of the
codes of the icon font.

An untagged PDF is left alone: it has no rule about the PUA, and its text keeps the
codes it always had.

This is a temporary shim. ``apply_actual_text_patch`` is idempotent and, if a future
WeasyPrint no longer exposes the patched internals, degrades to a no-op without ever
breaking PDF generation. Remove it once WeasyPrint writes an ActualText itself.
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import TYPE_CHECKING, Any

import pydyf  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_private_use_actual_text_patch"

# The Private Use Area of the Basic Multilingual Plane and the two supplementary ones, as
# code points: a class written with escapes of eight hex digits is misread by code scanners
PRIVATE_USE_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))
PRIVATE_USE = re.compile("[" + "".join(f"{chr(first)}-{chr(last)}" for first, last in PRIVATE_USE_RANGES) + "]+")


def _draw_module(name: str) -> Any | None:
    """Import a private WeasyPrint draw module, or return ``None``.

    These modules are internal to WeasyPrint. A future WeasyPrint that moves or drops
    one must not stop the service from starting.
    """
    try:
        return importlib.import_module(name)
    except ImportError:
        logger.warning("WeasyPrint module %r not found; ActualText patch degraded", name, exc_info=True)
        return None


weasyprint_draw = _draw_module("weasyprint.draw")
weasyprint_draw_text = _draw_module("weasyprint.draw.text")

# weasyprint.draw binds draw_text by name at import time, and draws every text box
# through that copy; weasyprint.draw.text holds the original.
_PATCHED_MODULES = tuple(module for module in (weasyprint_draw_text, weasyprint_draw) if module is not None)


def actual_text(text: str, element: Any) -> str | None:
    """The ActualText of a text box, or ``None`` when the box holds no PUA character."""
    if not PRIVATE_USE.search(text):
        return None
    rest = PRIVATE_USE.sub("", text)
    if rest.strip():
        return rest
    # Icons alone: the label of their element once, in place of the first, and the spaces
    # around them kept so the words beside the box do not run together in the extracted
    # text. The label is document content, so it is joined as text, never as a template.
    label = element.get("aria-label") if element is not None else None
    first, *others = PRIVATE_USE.split(text)
    return first + (label or "") + "".join(others)


def _with_actual_text(draw_text: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap draw_text so a text box with PUA characters carries an ActualText in a tagged PDF."""
    warned = False

    def wrapper(stream: Any, textbox: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal warned
        replacement: str | None = None
        try:
            # WeasyPrint keeps the marked content of a tagged PDF in _tags; an untagged one has none
            if getattr(stream, "_tags", None) is not None:
                replacement = actual_text(textbox.text or "", textbox.element)
        except Exception:
            # This branch means the box or stream API changed, so every box takes it. Warn
            # once per wrapper instead of once per box, or one conversion floods the log.
            if not warned:
                warned = True
                logger.warning("ActualText patch skipped for one text box; suppressing further warnings", exc_info=True)
            replacement = None
        if replacement is None:
            return draw_text(stream, textbox, *args, **kwargs)

        stream.begin_marked_content("Span", pydyf.Dictionary({"ActualText": pydyf.String(replacement)}))
        try:
            return draw_text(stream, textbox, *args, **kwargs)
        finally:
            stream.end_marked_content()

    setattr(wrapper, _PATCH_FLAG, True)
    return wrapper


def apply_actual_text_patch() -> bool:
    """Monkey-patch WeasyPrint so PUA characters carry an ActualText in a tagged PDF.

    Returns ``True`` when the patch is applied, ``False`` when it was already applied or
    the WeasyPrint internals could not be located.
    """
    if weasyprint_draw is None or weasyprint_draw_text is None or is_applied():
        return False

    original = getattr(weasyprint_draw_text, "draw_text", None)
    if original is None or getattr(weasyprint_draw, "draw_text", None) is None:
        logger.warning("WeasyPrint draw_text not found; ActualText patch skipped")
        return False

    patched = _with_actual_text(original)
    for module in _PATCHED_MODULES:
        module.draw_text = patched

    logger.info("Applied WeasyPrint ActualText patch (PUA characters carry an ActualText in a tagged PDF)")
    return True


def is_applied() -> bool:
    """Return whether the ActualText patch is installed."""
    return bool(_PATCHED_MODULES) and all(getattr(getattr(module, "draw_text", None), _PATCH_FLAG, False) for module in _PATCHED_MODULES)
