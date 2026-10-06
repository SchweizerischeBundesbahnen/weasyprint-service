"""Regression test for the WeasyPrint ActualText patch of Private Use Area characters."""

from pathlib import Path

import pymupdf
import pytest
import weasyprint
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app import weasyprint_actual_text_patch
from app.weasyprint_actual_text_patch import actual_text, apply_actual_text_patch, is_applied

# Apply the same fix the service applies at import of weasyprint_controller.
apply_actual_text_patch()

# The code Font Awesome 6 draws its "chart-column" icon with, in the Private Use Area
ICON = ""


@pytest.fixture(scope="module")
def icon_font(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A font of one square glyph at the code of the icon, as an icon font maps it."""
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "icon"])
    builder.setupCharacterMap({ord(ICON): "icon"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((100, 700))
    pen.lineTo((800, 700))
    pen.lineTo((800, 0))
    pen.closePath()
    square = pen.glyph()
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "icon": square})
    builder.setupHorizontalMetrics({".notdef": (500, 0), "icon": (900, 100)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Icons", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    path = tmp_path_factory.mktemp("font") / "icons.ttf"
    builder.save(str(path))
    return path


def _pdf(icon_font: Path, body: str, pdf_variant: str | None) -> bytes:
    html = f"""<html lang="en"><head><title>Icons</title><style>
        @font-face {{ font-family: Icons; src: url("{icon_font.as_uri()}"); }}
        .icon {{ font-family: Icons; }}
    </style></head><body>{body}</body></html>"""
    return weasyprint.HTML(string=html).write_pdf(pdf_variant=pdf_variant)


def _text(pdf: bytes) -> str:
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        return "".join(page.get_text() for page in document)


def _content(pdf: bytes) -> bytes:
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        return b"".join(page.read_contents() for page in document)


def test_patch_is_applied():
    assert is_applied()


@pytest.mark.parametrize("pdf_variant", ["pdf/a-2a", "pdf/a-3a", "pdf/ua-1", "pdf/ua-2"])
def test_an_icon_reads_as_nothing_in_a_tagged_pdf(icon_font, pdf_variant):
    pdf = _pdf(icon_font, f'<p><i class="icon">{ICON}</i>Version 1.0</p>', pdf_variant)

    assert b"/ActualText" in _content(pdf)
    text = _text(pdf)
    assert ICON not in text
    assert "Version 1.0" in text


def test_an_icon_reads_as_its_aria_label(icon_font):
    pdf = _pdf(icon_font, f'<p><i class="icon" aria-label="Plan">{ICON}</i> Version 1.0</p>', "pdf/a-2a")

    assert "Plan" in _text(pdf)


def test_the_spaces_around_an_icon_are_kept(icon_font):
    pdf = _pdf(icon_font, f'<p>Version<span class="icon"> {ICON} </span>1.0</p>', "pdf/a-2a")

    text = _text(pdf)
    assert ICON not in text
    assert "Version1.0" not in text.replace("\n", "")


def test_the_text_beside_an_icon_in_one_box_is_kept(icon_font):
    pdf = _pdf(icon_font, f'<p class="icon">a{ICON}b</p>', "pdf/a-2a")

    text = _text(pdf)
    assert ICON not in text
    assert "ab" in text


@pytest.mark.parametrize("pdf_variant", [None, "pdf/a-2b", "pdf/a-2u"])
def test_an_untagged_pdf_keeps_the_code_of_the_icon(icon_font, pdf_variant):
    pdf = _pdf(icon_font, f'<p><i class="icon">{ICON}</i>Version 1.0</p>', pdf_variant)

    assert b"/ActualText" not in _content(pdf)
    assert ICON in _text(pdf)


def test_text_without_private_use_characters_gets_no_actual_text(icon_font):
    pdf = _pdf(icon_font, "<p>Version 1.0</p>", "pdf/a-2a")

    assert b"/ActualText" not in _content(pdf)


@pytest.mark.parametrize(
    ("text", "label", "expected"),
    [
        ("Version", None, None),
        (ICON, None, ""),
        (ICON, "Plan", "Plan"),
        (f"a{ICON}b", "Plan", "ab"),
        (f" {ICON} ", None, "  "),
        (f" {ICON} ", "Plan", " Plan "),
        (f"{ICON}{ICON}", "Plan", "Plan"),
        (f"{ICON} {ICON}", "Plan", "Plan "),
        (f" {ICON} ", "C:\\Users", " C:\\Users "),
        (ICON, "v\\1 \\g<0>", "v\\1 \\g<0>"),
        ("\U000f0001", None, ""),
        ("\U00100001x", None, "x"),
    ],
)
def test_actual_text(text, label, expected):
    element = {"aria-label": label} if label else {}

    assert actual_text(text, element) == expected


def test_actual_text_without_element():
    assert actual_text(ICON, None) == ""


def test_patch_is_idempotent():
    assert apply_actual_text_patch() is False
    assert is_applied()


def test_missing_draw_module_degrades_to_none():
    assert weasyprint_actual_text_patch._draw_module("weasyprint.no_such_module") is None


def test_patch_skips_when_draw_text_is_missing(monkeypatch):
    monkeypatch.setattr(weasyprint_actual_text_patch, "is_applied", lambda: False)
    monkeypatch.delattr(weasyprint_actual_text_patch.weasyprint_draw_text, "draw_text")

    assert apply_actual_text_patch() is False


def test_a_changed_box_api_draws_as_before(monkeypatch, caplog):
    drawn = []
    wrapper = weasyprint_actual_text_patch._with_actual_text(lambda stream, textbox, *args: drawn.append(textbox))

    class Stream:
        _tags: dict = {}  # noqa: RUF012 - a stand-in for a tagged stream

    class Box:
        @property
        def text(self) -> str:
            raise AttributeError("text")

    wrapper(Stream(), Box())
    wrapper(Stream(), Box())

    assert len(drawn) == 2
    assert caplog.text.count("ActualText patch skipped") == 1
