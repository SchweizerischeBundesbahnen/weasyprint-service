"""A minimal VSDX drawing for the tests: one page with one rectangle filled in FILL_RGB.

The file is built here rather than committed, so its content stays reviewable.
"""

import io
import zipfile

FILL_RGB = (0x20, 0x60, 0xC0)

_VISIO = "http://schemas.microsoft.com/office/visio/2012/main"
_VISIO_REL = "http://schemas.microsoft.com/visio/2010/relationships"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _relationships(rel_type: str, target: str) -> str:
    return f'{_XML}<Relationships xmlns="{_PACKAGE_REL}"><Relationship Id="rId1" Type="{_VISIO_REL}/{rel_type}" Target="{target}"/></Relationships>'


def _rectangle_page() -> str:
    fill = "#{:02x}{:02x}{:02x}".format(*FILL_RGB)
    cells = {"PinX": 2, "PinY": 1.5, "Width": 3, "Height": 2, "LocPinX": 1.5, "LocPinY": 1, "FillPattern": 1, "LineWeight": 0.02}
    shape_cells = "".join(f'<Cell N="{name}" V="{value}"/>' for name, value in cells.items())
    points = [(0, 0), (3, 0), (3, 2), (0, 2), (0, 0)]
    rows = "".join(f'<Row T="{"MoveTo" if index == 1 else "LineTo"}" IX="{index}"><Cell N="X" V="{x}"/><Cell N="Y" V="{y}"/></Row>' for index, (x, y) in enumerate(points, start=1))
    return (
        f'{_XML}<PageContents xmlns="{_VISIO}" xmlns:r="{_OFFICE_REL}"><Shapes><Shape ID="1" Type="Shape">'
        f'{shape_cells}<Cell N="FillForegnd" V="{fill}"/><Cell N="LineColor" V="#000000"/>'
        f'<Section N="Geometry" IX="0">{rows}</Section></Shape></Shapes></PageContents>'
    )


def rectangle_vsdx() -> bytes:
    """The bytes of a VSDX file with one filled rectangle on one page."""
    parts = {
        "[Content_Types].xml": (
            f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
            '<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
            '<Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": _relationships("document", "visio/document.xml"),
        "visio/document.xml": f'{_XML}<VisioDocument xmlns="{_VISIO}" xmlns:r="{_OFFICE_REL}"/>',
        "visio/_rels/document.xml.rels": _relationships("pages", "pages/pages.xml"),
        "visio/pages/pages.xml": (
            f'{_XML}<Pages xmlns="{_VISIO}" xmlns:r="{_OFFICE_REL}"><Page ID="0" Name="Page-1" NameU="Page-1"><PageSheet><Cell N="PageWidth" V="4"/><Cell N="PageHeight" V="3"/></PageSheet><Rel r:id="rId1"/></Page></Pages>'
        ),
        "visio/pages/_rels/pages.xml.rels": _relationships("page", "page1.xml"),
        "visio/pages/page1.xml": _rectangle_page(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()
