"""Regression test for the WeasyPrint PDF/A gradient colour-space patch."""

from io import BytesIO

import pytest
import weasyprint
from PIL import Image

from app import weasyprint_pdfa_patch
from app.weasyprint_pdfa_patch import apply_pdfa_colorspace_patch, is_applied
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


def test_patch_is_installed():
    # Without this, the render tests above would pass silently on WeasyPrint versions
    # that draw the gradient even without the patch (e.g. 68.1), masking a fix that was
    # never installed. The patch must actually be in place.
    assert is_applied() is True


def test_patch_is_idempotent():
    # Already applied above, so a further call must be a no-op.
    assert apply_pdfa_colorspace_patch() is False


def test_apply_and_is_applied_when_stream_class_missing(monkeypatch):
    # A future WeasyPrint without a Stream class must fail safe, not raise at import.
    monkeypatch.setattr(weasyprint_pdfa_patch.weasyprint_stream, "Stream", None)
    assert apply_pdfa_colorspace_patch() is False
    assert is_applied() is False


@pytest.mark.parametrize(
    "attrs",
    [{}, {"add_shading": lambda *a, **k: None}],
    ids=["no-methods", "only-add_shading"],
)
def test_apply_skips_when_stream_methods_missing(monkeypatch, attrs):
    # If add_shading/add_group disappear, return a no-op instead of raising.
    monkeypatch.setattr(weasyprint_pdfa_patch.weasyprint_stream, "Stream", type("FakeStream", (), attrs))
    assert apply_pdfa_colorspace_patch() is False
    assert is_applied() is False


def test_patch_survives_internal_error(monkeypatch):
    # The wrappers must swallow an unexpected error and still produce a PDF.
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(weasyprint_pdfa_patch, "_color_space_value", boom)
    assert weasyprint.HTML(string=GRADIENT_HTML).write_pdf(pdf_variant="pdf/a-2b")


def test_color_space_value_for_non_icc_colours():
    # No matching ICC profile -> keep the bare /name (device colour spaces, etc.).
    assert weasyprint_pdfa_patch._color_space_value({}, "DeviceRGB") == "/DeviceRGB"
    profile_without_reference = type("Profile", (), {"pdf_reference": None})()
    assert weasyprint_pdfa_patch._color_space_value({"srgb": profile_without_reference}, "srgb") == "/srgb"
