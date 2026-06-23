"""Regression test for the WeasyPrint PDF/A gradient colour-space patch."""

from io import BytesIO

import pytest
import weasyprint
from PIL import Image

from app.weasyprint_pdfa_patch import apply_pdfa_colorspace_patch
from tests import utils_pdf

# Apply the same fix the service applies at import of weasyprint_controller.
apply_pdfa_colorspace_patch()

# A page whose only visible content is a CSS linear-gradient background.
GRADIENT_HTML = '<!doctype html><html><body style="margin:20px"><div style="width:200px;height:100px;background:linear-gradient(135deg,#11998e 0%,#38ef7d 100%)"></div></body></html>'

# Every PDF/A variant the service supports drives colours through the sRGB output
# intent, so the WeasyPrint 69.0 regression affects all of them identically.
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


def _painted_pixels(png_bytes: bytes) -> int:
    """Count pixels darker than near-white (i.e. actually painted)."""
    image = Image.open(BytesIO(png_bytes)).convert("L")
    return sum(image.histogram()[:240])


@pytest.mark.parametrize("pdf_variant", PDFA_VARIANTS)
def test_pdfa_gradient_is_rendered(pdf_variant):
    # WeasyPrint 69.0 dropped linear-gradient backgrounds from PDF/A because the
    # gradient shading colour space was written as a bare /srgb name that readers
    # cannot resolve. With the patch it is a direct ICCBased colour space, so the
    # gradient must actually paint for every PDF/A variant.
    pdf_bytes = weasyprint.HTML(string=GRADIENT_HTML).write_pdf(pdf_variant=pdf_variant)
    pages = utils_pdf.pdf_bytes_to_png_pages(pdf_bytes, zoom=1.5)
    assert _painted_pixels(pages[0]) > 500


def test_patch_is_idempotent():
    # Already applied above, so a further call must be a no-op.
    assert apply_pdfa_colorspace_patch() is False
