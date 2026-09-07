"""Regression test for the WeasyPrint running-element intrinsic-width patch."""

import pymupdf
import pytest
import weasyprint

from app import weasyprint_running_width_patch
from app.weasyprint_running_width_patch import apply_running_width_patch, is_applied

# Apply the same fix the service applies at import of weasyprint_controller.
apply_running_width_patch()

# A block-level running element holding text. Without the patch, every intrinsic-width
# (shrink-to-fit) wrapper below makes WeasyPrint recurse into it, reach the bare TextBox
# that inline_in_block never wrapped in a line box, and raise
# TypeError: min-content width for TextBox not handled yet.
RUNNING_ELEMENT = '<div style="position:running(header)">RUNNINGTEXT</div>'

SHRINK_TO_FIT_WRAPPERS = {
    "float": f'<div style="float:left">{RUNNING_ELEMENT}WRAPPERTEXT</div>',
    "inline-block": f'<div style="display:inline-block">{RUNNING_ELEMENT}WRAPPERTEXT</div>',
    "absolute": f'<div style="position:absolute">{RUNNING_ELEMENT}WRAPPERTEXT</div>',
    "table-cell": f"<table><tr><td>{RUNNING_ELEMENT}WRAPPERTEXT</td></tr></table>",
    "flex-item": f'<div style="display:flex;width:min-content"><div>{RUNNING_ELEMENT}WRAPPERTEXT</div></div>',
    "nested-float": f'<div style="float:left"><div><section>{RUNNING_ELEMENT}</section></div>WRAPPERTEXT</div>',
}

# The margin box that consumes the running element is not needed to trigger the crash,
# so the wrapper cases above leave it out. This page has it, to check the patch does not
# cost the running element its content.
MARGIN_BOX_HTML = f'<!doctype html><html><head><style>@page{{size:400px 300px;margin:40px;@top-center{{content:element(header)}}}}</style></head><body><div style="float:left">{RUNNING_ELEMENT}WRAPPERTEXT</div>BODYTEXT</body></html>'


def _page_words(pdf_bytes: bytes) -> list[tuple[float, float, str]]:
    """Return the first page's words as (x, y, text), in reading order."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        return [(word[0], word[1], word[4]) for word in document[0].get_text("words")]


@pytest.mark.parametrize("wrapper", SHRINK_TO_FIT_WRAPPERS.values(), ids=list(SHRINK_TO_FIT_WRAPPERS))
def test_running_element_in_shrink_to_fit_box_converts(wrapper):
    # Each of these raised TypeError before the patch, which the service reported as a 500.
    pdf_bytes = weasyprint.HTML(string=f"<!doctype html><html><body>{wrapper}</body></html>").write_pdf()
    assert pdf_bytes
    assert any("WRAPPERTEXT" in text for _, _, text in _page_words(pdf_bytes))


def test_running_element_still_reaches_its_margin_box():
    # The patch removes the running element from the intrinsic-width calculation only.
    # Its content must still be moved into the page margin box, above the body content.
    words = _page_words(weasyprint.HTML(string=MARGIN_BOX_HTML).write_pdf())
    running = [(x, y) for x, y, text in words if "RUNNINGTEXT" in text]
    body = [(x, y) for x, y, text in words if "BODYTEXT" in text]
    assert running, f"running element content is missing from the page: {words}"
    assert body, f"body content is missing from the page: {words}"
    assert running[0][1] < 40, "running element content is not in the top margin box"
    assert running[0][1] < body[0][1]


def test_document_without_running_elements_is_unaffected():
    # The wrappers must stay shrink-to-fit: a float around plain text keeps its width.
    html = '<!doctype html><html><body><div style="float:left">WRAPPERTEXT</div></body></html>'
    assert any("WRAPPERTEXT" in text for _, _, text in _page_words(weasyprint.HTML(string=html).write_pdf()))


def test_patch_is_installed():
    # Without this, the render tests above would pass silently on a WeasyPrint version
    # whose internals moved, masking a fix that was never installed.
    assert is_applied() is True


def test_patch_is_idempotent():
    # Already applied above, so a further call must be a no-op.
    assert apply_running_width_patch() is False


def test_apply_skips_when_intrinsic_width_functions_missing(monkeypatch):
    # A future WeasyPrint without these functions must fail safe, not raise at import.
    monkeypatch.delattr(weasyprint_running_width_patch.weasyprint_preferred, "table_cell_min_content_width")
    assert apply_running_width_patch() is False
    assert is_applied() is False


def test_patch_survives_a_box_without_is_running(monkeypatch):
    # An unexpected box type must not break PDF generation.
    class BoxWithoutIsRunning:
        def is_running(self):
            raise AttributeError("no is_running")

    wrapped = weasyprint_running_width_patch._zero_for_running(lambda context, box: 42, 0)
    assert wrapped(None, BoxWithoutIsRunning()) == 42
