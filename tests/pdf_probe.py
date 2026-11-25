"""Read what the tests check in a PDF: text, words, images, forms and filled vector paths.

Backed by pypdfium2. Positions are in pt, with the origin at the top left of the page.
"""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

import pypdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class Box:
    """A rectangle on the page, in pt, measured from the top left corner."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class Word:
    """A run of characters between spaces or line breaks."""

    box: Box
    text: str


@contextmanager
def open_pdf(data: bytes) -> Iterator[pdfium.PdfDocument]:
    """Open PDF bytes and close the document when the block ends."""
    document = pdfium.PdfDocument(data)
    try:
        yield document
    finally:
        document.close()


def _box(page: pdfium.PdfPage, left: float, bottom: float, right: float, top: float) -> Box:
    height = page.get_height()
    return Box(left, height - top, right, height - bottom)


def _objects_on_page(
    page: pdfium.PdfPage,
    form: pdfium.PdfObject | None = None,
    to_page: pdfium.PdfMatrix | None = None,
) -> Iterator[tuple[pdfium.PdfObject, pdfium.PdfMatrix | None]]:
    """Yield each object with the matrix from its form space to page space, None on the page itself.

    PDFium gives the bounds of an object inside a form XObject in the space of that form.
    """
    for obj in page.get_objects(max_depth=0, form=form):
        yield obj, to_page
        if obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            form_to_page = obj.get_matrix() if to_page is None else obj.get_matrix().multiply(to_page)
            yield from _objects_on_page(page, obj, form_to_page)


def _path_bounds(path: pdfium.PdfObject, to_page: pdfium.PdfMatrix | None) -> tuple[float, float, float, float]:
    """Return the bounds of the geometry of a path in page space, without the width of its stroke.

    PDFium widens the bounds of a stroked path by its line width. A test measures the shape itself.
    """
    to_space = path.get_matrix() if to_page is None else path.get_matrix().multiply(to_page)
    points = []
    for index in range(pdfium_c.FPDFPath_CountSegments(path.raw)):
        segment = pdfium_c.FPDFPath_GetPathSegment(path.raw, index)
        x, y = ctypes.c_float(), ctypes.c_float()
        pdfium_c.FPDFPathSegment_GetPoint(segment, ctypes.byref(x), ctypes.byref(y))
        points.append(to_space.on_point(x.value, y.value))
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def filled_paths(page: pdfium.PdfPage) -> list[tuple[tuple[float, float, float], Box]]:
    """Return the fill color, as RGB from 0 to 1, and the box of each filled path, forms included."""
    paths = []
    for path, to_page in _objects_on_page(page):
        if path.type != pdfium_c.FPDF_PAGEOBJ_PATH:
            continue
        fill_mode, stroke = ctypes.c_int(), ctypes.c_int()
        pdfium_c.FPDFPath_GetDrawMode(path.raw, ctypes.byref(fill_mode), ctypes.byref(stroke))
        if fill_mode.value == pdfium_c.FPDF_FILLMODE_NONE:
            continue
        red, green, blue, alpha = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        if not pdfium_c.FPDFPageObj_GetFillColor(path.raw, ctypes.byref(red), ctypes.byref(green), ctypes.byref(blue), ctypes.byref(alpha)):
            continue
        color = (red.value / 255, green.value / 255, blue.value / 255)
        paths.append((color, _box(page, *_path_bounds(path, to_page))))
    return paths


def image_count(page: pdfium.PdfPage) -> int:
    """Count the images drawn on the page, forms included."""
    return sum(1 for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))


def has_form(page: pdfium.PdfPage) -> bool:
    """Tell whether the page draws a form XObject."""
    return any(True for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_FORM]))


def text(page: pdfium.PdfPage) -> str:
    """Return the text of the page, as a reader extracts it."""
    textpage = page.get_textpage()
    try:
        return textpage.get_text_bounded()
    finally:
        textpage.close()


def words(page: pdfium.PdfPage) -> list[Word]:
    """Return the words of the page in reading order. A space or a line break ends a word."""
    textpage = page.get_textpage()
    try:
        found: list[Word] = []
        chars: list[str] = []
        boxes: list[tuple[float, float, float, float]] = []

        def flush() -> None:
            if chars:
                left = min(box[0] for box in boxes)
                bottom = min(box[1] for box in boxes)
                right = max(box[2] for box in boxes)
                top = max(box[3] for box in boxes)
                found.append(Word(_box(page, left, bottom, right, top), "".join(chars)))
            chars.clear()
            boxes.clear()

        for index in range(textpage.count_chars()):
            char = textpage.get_text_range(index, 1)
            if not char or char.isspace():
                flush()
                continue
            chars.append(char)
            boxes.append(textpage.get_charbox(index, loose=True))
        flush()
        return found
    finally:
        textpage.close()


def find_text(page: pdfium.PdfPage, needle: str) -> Box:
    """Return the box of the first occurrence of NEEDLE on the page."""
    textpage = page.get_textpage()
    try:
        searcher = textpage.search(needle, match_case=True)
        match = searcher.get_next()
        if match is None:
            msg = f"{needle!r} is not on the page"
            raise AssertionError(msg)
        first, count = match
        left, bottom, _, top = textpage.get_charbox(first, loose=True)
        _, _, right, _ = textpage.get_charbox(first + count - 1, loose=True)
        return _box(page, left, bottom, right, top)
    finally:
        textpage.close()


def page_contents(data: bytes) -> list[bytes]:
    """Return the raw content stream of each page, without the forms it draws."""
    reader = pypdf.PdfReader(BytesIO(data))
    contents = []
    for page in reader.pages:
        stream = page.get_contents()
        contents.append(stream.get_data() if stream is not None else b"")
    return contents
