#!/usr/bin/env python3
"""
Minimal reproduction + validation: WeasyPrint crashes on a running element that
sits inside a shrink-to-fit box.

A block-level ``position: running(name)`` element holding text raises
``TypeError: min-content width for TextBox not handled yet`` whenever an
intrinsic-width container asks for its width. WeasyPrint never wraps a running
element's text in a line box (``inline_in_block`` returns early for a running
box), and the intrinsic-width walk in ``layout/preferred.py`` filters out only
absolutely positioned children, so it recurses into the running box and reaches
a bare ``TextBox`` it has no branch for.

The script renders the same running element under every intrinsic-width wrapper
and reports which ones convert. Run once per WeasyPrint version (``uv`` makes
this a one-liner; the WeasyPrint system libraries - pango/cairo/... - must be
present):

    uv run --with 'weasyprint==69.0' repro_running_element.py
    uv run --with 'weasyprint==69.0' repro_running_element.py --patch

``--patch`` applies the weasyprint-service workaround
(app/weasyprint_running_width_patch.py). Use it to validate, on any future
WeasyPrint, that the service fix still converts these documents - and run
without it to check whether upstream has fixed the bug.

Expected on 69.0: every wrapper CRASHES without ``--patch``, every wrapper
CONVERTS with it.
"""

from __future__ import annotations

import pathlib
import sys

import weasyprint

# The wrapper style that replaces "float: left" in running_element.html. Each one
# puts the running element into an intrinsic-width (shrink-to-fit) context.
WRAPPER_STYLES = [
    "float: left",
    "display: inline-block",
    "position: absolute",
]

# The markup of the wrapper in running_element.html, and the two wrappers that need
# their own markup rather than a style: an auto-layout table cell, and a flex item
# (the running element must be *inside* the item, not be the item itself).
WRAPPER_OPEN = '<div style="float: left">'
WRAPPER_CLOSE = "</div>\n    BODYTEXT"
MARKUP_WRAPPERS = {
    "table cell": ("<table><tr><td>", "</td></tr></table>\n    BODYTEXT"),
    "flex item": ('<div style="display: flex; width: min-content"><div>', "</div></div>\n    BODYTEXT"),
}

# The page margin in running_element.html. Text above it is inside the top margin box.
PAGE_MARGIN_PX = 40

patched = "--patch" in sys.argv
if patched:
    # Apply the weasyprint-service fix from its single source of truth.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from app.weasyprint_running_width_patch import apply_running_width_patch

    apply_running_width_patch()

template = pathlib.Path(__file__).with_name("running_element.html").read_text()


def documents() -> dict[str, str]:
    """Return one document per intrinsic-width wrapper, keyed by wrapper name."""
    result = {style: template.replace("float: left", style) for style in WRAPPER_STYLES}
    for name, (opening, closing) in MARKUP_WRAPPERS.items():
        result[name] = template.replace(WRAPPER_OPEN, opening).replace(WRAPPER_CLOSE, closing)
    return result


def running_text_position(pdf_bytes: bytes) -> str:
    """Report where the running element's text ended up, if pymupdf is available."""
    try:
        import pymupdf
    except ImportError:
        return ""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for word in document[0].get_text("words"):
            if "RUNNINGTEXT" in word[4]:
                where = "top margin box" if word[1] < PAGE_MARGIN_PX else f"page body (y={word[1]:.1f})"
                return f", running text in {where}"
    return ", running text MISSING"


label = f"{weasyprint.__version__}{'+patch' if patched else ''}"
print(f"weasyprint {label}")
for name, html in documents().items():
    try:
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    except Exception as error:  # noqa: BLE001
        print(f"  {name:32} ->  CRASHES: {type(error).__name__}: {error}")
    else:
        print(f"  {name:32} ->  CONVERTS ok ({len(pdf_bytes)} bytes{running_text_position(pdf_bytes)})")
