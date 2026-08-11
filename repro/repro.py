#!/usr/bin/env python3
"""
Minimal reproduction + validation: WeasyPrint drops CSS ``linear-gradient``
backgrounds when writing PDF/A.

WeasyPrint 68.1 emits the gradient shading in ``/DeviceRGB``        -> renders fine.
WeasyPrint 69.0 (new PDF output-intent / ICC colour management,
#2631/#2778/#2785/#2788) emits it in a *named* ICCBased colour space ``/srgb``
-> common PDF readers (pdfium / MuPDF, Apache PDFBox, ...) report
``unknown colorspace: srgb`` and the gradient simply disappears.

It renders the gradient with *every* supported PDF/A variant and reports, for
each, the gradient shading's colour space and whether the gradient actually
paints. Run once per WeasyPrint version (``uv`` makes this a one-liner; the
WeasyPrint system libraries — pango/cairo/… — must be present):

    uv run --with 'weasyprint==68.1' --with pymupdf repro.py
    uv run --with 'weasyprint==69.0' --with pymupdf repro.py
    uv run --with 'weasyprint==69.0' --with pymupdf repro.py --patch

``--patch`` applies the weasyprint-service workaround (app/weasyprint_pdfa_patch.py).
Use it to validate, on any future WeasyPrint, that the service fix still renders the
gradient — and run without it to check whether upstream has fixed the bug.

Expected on 69.0: every variant BLANK without ``--patch``, every variant RENDERED
with it; on 68.1 every variant renders.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pymupdf  # PyMuPDF
import weasyprint

NEAR_WHITE_RGB_SUM = 730  # R+G+B at/above this counts as white (i.e. unpainted)
MIN_PAINTED_PIXELS = 500  # at least this many painted pixels = gradient rendered

# Every PDF/A variant the weasyprint-service supports (all drive colours through
# the sRGB output intent, so the 69.0 regression hits them identically).
PDFA_VARIANTS = [
    "pdf/a-1b",
    "pdf/a-1a",
    "pdf/a-2b",
    "pdf/a-2u",
    "pdf/a-2a",
    "pdf/a-3b",
    "pdf/a-3u",
    "pdf/a-3a",
    "pdf/a-4u",
    "pdf/a-4e",
    "pdf/a-4f",
]

patched = "--patch" in sys.argv
if patched:
    # Apply the weasyprint-service fix from its single source of truth.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from app.weasyprint_pdfa_patch import apply_pdfa_colorspace_patch

    apply_pdfa_colorspace_patch()

html = pathlib.Path(__file__).with_name("gradient.html").read_text()


def shading_color_space(doc: pymupdf.Document) -> str:
    """Return the gradient shading's ColorSpace as written in the PDF."""
    for xref in range(1, doc.xref_length()):
        obj = doc.xref_object(xref, compressed=True)
        if "/ShadingType" in obj:
            match = re.search(r"/ColorSpace\s*(\[[^\]]*\]|/[A-Za-z0-9.\-]+)", obj)
            return match.group(1) if match else "(inline)"
    return "(no shading found)"


def is_rendered(doc: pymupdf.Document) -> bool:
    """Rasterise the first page and report whether the gradient actually paints."""
    pixmap = doc[0].get_pixmap(dpi=72)
    samples = pixmap.samples
    channels = pixmap.n
    painted = 0
    for i in range(0, len(samples), channels):
        if samples[i] + samples[i + 1] + samples[i + 2] < NEAR_WHITE_RGB_SUM:
            painted += 1
            if painted > MIN_PAINTED_PIXELS:
                return True
    return False


label = f"{weasyprint.__version__}{'+patch' if patched else ''}"
print(f"weasyprint {label}")
for variant in PDFA_VARIANTS:
    pdf_bytes = weasyprint.HTML(string=html).write_pdf(pdf_variant=variant)
    if variant == "pdf/a-2b":  # keep one representative PDF for visual inspection
        pathlib.Path(__file__).with_name(f"gradient_{variant.replace('/', '-')}_{label}.pdf").write_bytes(pdf_bytes)
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    status = "RENDERED ok" if is_rendered(doc) else "BLANK (gradient dropped)"
    print(f"  {variant:<9} shading ColorSpace = {shading_color_space(doc):<18} ->  {status}")
