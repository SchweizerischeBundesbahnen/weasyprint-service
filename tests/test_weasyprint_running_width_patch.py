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
# cost the running element its content. The running text is a parameter, because its
# length is what tells a working @top-center from a collapsed one.
MARGIN_BOX_TEMPLATE = (
    "<!doctype html><html><head><style>@page{{size:400px 300px;margin:40px;@top-center{{content:element(header)}}}}</style></head>"
    '<body><div style="float:left"><div style="position:running(header)">{running}</div>WRAPPERTEXT</div>BODYTEXT</body></html>'
)

PAGE_MARGIN_PX = 40


def _page_words(pdf_bytes: bytes) -> list[tuple[float, float, float, str]]:
    """Return the first page's words as (left, top, right, text), in reading order."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        return [(word[0], word[1], word[2], word[4]) for word in document[0].get_text("words")]


def _word(words, needle):
    """Return the first word containing ``needle``, or fail with the whole page."""
    for word in words:
        if needle in word[3]:
            return word
    raise AssertionError(f"{needle} is missing from the page: {words}")


@pytest.mark.parametrize("wrapper", SHRINK_TO_FIT_WRAPPERS.values(), ids=list(SHRINK_TO_FIT_WRAPPERS))
def test_running_element_in_shrink_to_fit_box_converts(wrapper):
    # Each of these raised TypeError before the patch, which the service reported as a 500.
    pdf_bytes = weasyprint.HTML(string=f"<!doctype html><html><body>{wrapper}</body></html>").write_pdf()
    assert pdf_bytes
    assert _word(_page_words(pdf_bytes), "WRAPPERTEXT")


def _margin_box_running_word(running_text):
    """Render the margin-box page and return its running word, as (left, top, right)."""
    words = _page_words(weasyprint.HTML(string=MARGIN_BOX_TEMPLATE.format(running=running_text)).write_pdf())
    return _word(words, running_text[:11]), _word(words, "BODYTEXT")


def test_running_element_still_reaches_its_margin_box():
    # The patch removes the running element from the intrinsic-width calculation only.
    # Its content must still be moved into the page margin box, above the body content.
    running, body = _margin_box_running_word("RUNNINGTEXT")
    assert running[1] < PAGE_MARGIN_PX, f"running element content is not in the top margin box: {running}"
    assert running[1] < body[1]


def test_margin_box_keeps_its_width():
    # @top-center sizes itself from the running content's own intrinsic width, which is
    # exactly what this patch returns zero for, so a collapsed margin box is the
    # regression to catch. A centred box keeps the text centred on the same point
    # whatever its length; a zero-width box anchors the text at that point and lets it
    # overflow to the right, which moves the centre as the text grows. Comparing two
    # lengths tests that without hard-coding a position WeasyPrint is free to change.
    short, _ = _margin_box_running_word("RUNNINGTEXT")
    long, _ = _margin_box_running_word("RUNNINGTEXTRUNNINGTEXTRUNNING")
    assert long[2] - long[0] > short[2] - short[0], "the two runs must differ in width for this test to mean anything"
    short_centre = (short[0] + short[2]) / 2
    long_centre = (long[0] + long[2]) / 2
    assert abs(short_centre - long_centre) < 1, f"the margin box collapsed: centres {short_centre} and {long_centre}"


def test_document_without_running_elements_is_unaffected():
    # A float around plain text must keep its width: the following text has to start at
    # the float's right edge, not back at the page margin. The 20px margin on the float
    # is what keeps the two runs far enough apart to be read as separate words.
    html = '<!doctype html><html><body><div style="float:left;margin-right:20px">WRAPPERTEXT</div><p>BODYTEXT</p></body></html>'
    words = _page_words(weasyprint.HTML(string=html).write_pdf())
    wrapper = _word(words, "WRAPPERTEXT")
    body = _word(words, "BODYTEXT")
    assert body[0] >= wrapper[2], f"the float did not displace the text after it: {words}"


def test_patch_is_installed():
    # Without this, the render tests above would pass silently on a WeasyPrint version
    # whose internals moved, masking a fix that was never installed.
    assert is_applied() is True


def test_patch_is_idempotent():
    # Already applied above, so a further call must be a no-op.
    assert apply_running_width_patch() is False


def test_layout_module_import_failure_returns_none():
    # The private WeasyPrint layout modules are imported through this helper so a
    # future rename cannot stop the service from starting.
    assert weasyprint_running_width_patch._layout_module("no_such_layout_module") is None


def test_apply_skips_when_the_layout_module_is_missing(monkeypatch):
    # Same, from the caller's side: no weasyprint.layout.preferred means a no-op.
    monkeypatch.setattr(weasyprint_running_width_patch, "weasyprint_preferred", None)
    assert apply_running_width_patch() is False
    assert is_applied() is False


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
