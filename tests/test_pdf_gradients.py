"""Render tests for CSS gradients in plain and PDF/A output."""

import importlib
from io import BytesIO

import pytest
import weasyprint
from PIL import Image

from tests import utils_pdf

# Install the WeasyPrint patches the service applies at import, so these tests render
# through the same stack as production and do not depend on test collection order.
importlib.import_module("app.weasyprint_controller")

# A page whose only visible content is a CSS linear-gradient background.
GRADIENT_HTML = '<!doctype html><html><body style="margin:20px"><div style="width:200px;height:100px;background:linear-gradient(135deg,#11998e 0%,#38ef7d 100%)"></div></body></html>'

# The same gradient with opacity, so WeasyPrint also writes a transparency group.
TRANSLUCENT_GRADIENT_HTML = '<!doctype html><html><body style="margin:20px"><div style="opacity:0.6;width:200px;height:100px;background:linear-gradient(135deg,#11998e 0%,#38ef7d 100%)"></div></body></html>'

# None is plain PDF. The PDF/A variants write colors through the sRGB output intent.
PDF_VARIANTS = [
    None,
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


def _painted_pixels(png_bytes: bytes) -> int:
    """Count pixels darker than near-white (i.e. actually painted)."""
    image = Image.open(BytesIO(png_bytes)).convert("L")
    return sum(image.histogram()[:240])


@pytest.mark.parametrize("html", [GRADIENT_HTML, TRANSLUCENT_GRADIENT_HTML], ids=["opaque", "translucent"])
@pytest.mark.parametrize("pdf_variant", PDF_VARIANTS, ids=lambda variant: variant or "plain")
def test_gradient_is_rendered(pdf_variant, html):
    # WeasyPrint 69.0 wrote the shading and group color space of a PDF/A gradient as a
    # bare /srgb name, which readers cannot resolve, so the gradient disappeared.
    # WeasyPrint 70.0 fixed it upstream. The gradient must paint in every variant.
    pdf_bytes = weasyprint.HTML(string=html).write_pdf(pdf_variant=pdf_variant)
    pages = utils_pdf.pdf_bytes_to_png_pages(pdf_bytes, zoom=1.5)
    assert _painted_pixels(pages[0]) > 500
