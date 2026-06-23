#!/usr/bin/env python3
"""
Minimal reproduction: WeasyPrint drops CSS ``linear-gradient`` backgrounds when
writing PDF/A.

WeasyPrint 68.1 emits the gradient shading in ``/DeviceRGB``        -> renders fine.
WeasyPrint 69.0 (new PDF output-intent / ICC colour management,
#2631/#2778/#2785/#2788) emits it in a *named* ICCBased colour space ``/srgb``
-> common PDF readers (pdfium / MuPDF, Apache PDFBox, ...) report
``unknown colorspace: srgb`` and the gradient simply disappears.

Run it once with each WeasyPrint version (``uv`` makes this a one-liner; the
WeasyPrint system libraries — pango/cairo/… — must be present):

    uv run --with 'weasyprint==68.1' --with pymupdf repro.py
    uv run --with 'weasyprint==69.0' --with pymupdf repro.py

Expected output:

    weasyprint 68.1 : gradient shading ColorSpace = /DeviceRGB  ->  RENDERED ok
    weasyprint 69.0 : gradient shading ColorSpace = /srgb       ->  BLANK (gradient dropped)
"""

import pathlib
import re

import pymupdf  # PyMuPDF
import weasyprint

HTML = pathlib.Path(__file__).with_name("gradient.html").read_text()

# Render to PDF/A-2b (this is what triggers the output-intent / ICC colour space).
pdf_bytes = weasyprint.HTML(string=HTML).write_pdf(pdf_variant="pdf/a-2b")

version = weasyprint.__version__
out = pathlib.Path(__file__).with_name(f"gradient_pdfa_{version}.pdf")
out.write_bytes(pdf_bytes)

doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

# 1) Which colour space did WeasyPrint assign to the gradient's shading object?
shading_cs = "(no shading found)"
for xref in range(1, doc.xref_length()):
    obj = doc.xref_object(xref, compressed=True)
    if "/ShadingType" in obj:
        m = re.search(r"/ColorSpace\s*(/[A-Za-z0-9.\-]+)", obj)
        shading_cs = m.group(1) if m else "(inline array)"
        break

# 2) Does the gradient actually paint? Rasterise and look for any non-white pixel.
pix = doc[0].get_pixmap(dpi=96)
n = pix.n
data = pix.samples
painted = 0
for i in range(0, len(data), n):
    if data[i] + data[i + 1] + data[i + 2] < 730:  # anything that is not white
        painted += 1
        if painted > 500:
            break
rendered = painted > 500

print(f"weasyprint {version} : gradient shading ColorSpace = {shading_cs:<11} ->  {'RENDERED ok' if rendered else 'BLANK (gradient dropped)'}   [{painted} painted px, saved {out.name}]")
