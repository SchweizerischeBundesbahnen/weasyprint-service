"""An SVG image the document limits in height keeps the alignment of its table column; #409."""

import base64

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.weasyprint_controller import app

# 80x600 px: max-height shortens it, and its width follows
TALL_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="600" viewBox="0 0 80 600"><rect x="2" y="2" width="76" height="596" fill="#1a73e8"/></svg>'
SOURCE = "data:image/svg+xml;base64," + base64.b64encode(TALL_SVG.encode()).decode()
ALIGNMENTS = ("left", "center", "right")
CELL = "vertical-align: top; border: 1px solid #ccc; padding: 5px; width: 33%;"
TOLERANCE_PT = 1.5
BLUE = (0x1A / 255, 0x73 / 255, 0xE8 / 255)


def _html() -> str:
    """A column per alignment, each with a word flush left and one flush right to mark its edges, then the image.

    The image states no size and is limited in height, as the PDF exporter fits an image to the page.
    """
    cells = "".join(
        f'<td style="{CELL} text-align: {align};"><div style="text-align: left;">Start{i}</div><div style="text-align: right;">End{i}</div><img src="{SOURCE}" style="max-width: 650px; max-height: 200px; object-fit: contain;"/></td>'
        for i, align in enumerate(ALIGNMENTS)
    )
    return f'<html><body><table style="width: 100%; table-layout: fixed; border-collapse: collapse;"><tr>{cells}</tr></table></body></html>'


def test_a_shortened_svg_keeps_the_alignment_of_its_column() -> None:
    with TestClient(app) as test_client:
        result = test_client.post("/convert/html", content=_html())
    assert result.status_code == 200

    with pymupdf.open(stream=result.content, filetype="pdf") as doc:
        page = doc[0]
        # weasysvg draws the SVG as vector: the blue rectangle of each image is a filled path
        drawn = sorted((drawing["rect"] for drawing in page.get_drawings() if drawing["fill"] and drawing["fill"] == pytest.approx(BLUE, abs=0.01)), key=lambda rect: rect.x0)
        assert len(drawn) == len(ALIGNMENTS)
        for i, (align, image) in enumerate(zip(ALIGNMENTS, drawn, strict=True)):
            left = page.search_for(f"Start{i}")[0].x0
            right = page.search_for(f"End{i}")[0].x1
            # The drawing is shortened to 200 px, 150 pt, and narrowed with it: 20 pt, not the 60 pt of the SVG.
            # The rectangle sits 2 px inside the 80x600 SVG, which the tolerance covers.
            assert image.height == pytest.approx(150, abs=TOLERANCE_PT)
            assert image.width == pytest.approx(20, abs=TOLERANCE_PT)
            gaps = f"{align}: column {left:.1f}-{right:.1f} pt, image {image.x0:.1f}-{image.x1:.1f} pt"
            if align == "left":
                assert image.x0 == pytest.approx(left, abs=TOLERANCE_PT), gaps
            elif align == "right":
                assert image.x1 == pytest.approx(right, abs=TOLERANCE_PT), gaps
            else:
                assert image.x0 - left == pytest.approx(right - image.x1, abs=TOLERANCE_PT), gaps
