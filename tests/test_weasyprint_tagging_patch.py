"""Regression test for the WeasyPrint patch tagging links and images as PDF/UA requires."""

import io

import pymupdf
import pypdf
import pytest
import weasyprint

from app import weasyprint_tagging_patch
from app.weasyprint_tagging_patch import apply_tagging_patch, is_applied, is_decorative

# Apply the same fix the service applies at import of weasyprint_controller.
apply_tagging_patch()

# A red pixel, an image any HTML may show
PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="


def _pdf(body: str, pdf_variant: str | None = "pdf/ua-1") -> bytes:
    html = f'<html lang="en"><head><title>Tagging</title></head><body>{body}</body></html>'
    return weasyprint.HTML(string=html).write_pdf(pdf_variant=pdf_variant)


def _structure(pdf: bytes) -> tuple[pypdf.PdfReader, list[pypdf.generic.DictionaryObject]]:
    """The reader of a tagged PDF and every element of its structure tree."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    elements: list[pypdf.generic.DictionaryObject] = []

    def walk(node: object) -> None:
        node = node.get_object() if hasattr(node, "get_object") else node
        if isinstance(node, pypdf.generic.ArrayObject):
            for kid in node:
                walk(kid)
        elif isinstance(node, pypdf.generic.DictionaryObject) and "/S" in node:
            elements.append(node)
            walk(node.get("/K"))

    walk(reader.trailer["/Root"]["/StructTreeRoot"]["/K"])
    return reader, elements


def _parent_tree(reader: pypdf.PdfReader) -> dict[int, object]:
    nums = reader.trailer["/Root"]["/StructTreeRoot"]["/ParentTree"].get_object()["/Nums"]
    return {int(nums[index]): nums[index + 1].get_object() for index in range(0, len(nums), 2)}


def _link_annotations(reader: pypdf.PdfReader) -> list[pypdf.generic.DictionaryObject]:
    return [annotation.get_object() for page in reader.pages for annotation in page.get("/Annots", []) if annotation.get_object()["/Subtype"] == "/Link"]


def _holds(element: pypdf.generic.DictionaryObject, annotation: pypdf.generic.DictionaryObject) -> bool:
    """Whether an element holds the object reference of an annotation among its kids."""
    kids = element.get("/K")
    kids = kids if isinstance(kids, pypdf.generic.ArrayObject) else [kids]
    for kid in kids:
        resolved = kid.get_object() if hasattr(kid, "get_object") else kid
        if isinstance(resolved, pypdf.generic.DictionaryObject) and resolved.get("/Type") == "/OBJR" and resolved["/Obj"].get_object() == annotation:
            return True
    return False


def test_patch_is_applied():
    assert is_applied()


@pytest.mark.parametrize(
    "link",
    [
        '<a href="#target"><span>1</span> <span>Introduction</span></a>',
        f'<a href="https://example.com"><img src="{PIXEL}" alt="" style="width:8px"><span>EL-1</span> - <span>Title</span></a>',
        f'<a href="https://example.com"><img src="{PIXEL}" alt="Icon" style="width:8px">Text</a>',
    ],
)
def test_every_link_annotation_is_held_by_a_link(link):
    pdf = _pdf(f'<p>{link}</p><p id="target">Target</p>')

    reader, _ = _structure(pdf)
    annotations = _link_annotations(reader)
    holders = _parent_tree(reader)
    assert len(annotations) > 1, "The link holding other elements gets several annotations"
    for annotation in annotations:
        holder = holders[int(annotation["/StructParent"])]
        assert holder["/S"] == "/Link"
        assert _holds(holder, annotation)


def test_a_decorative_image_is_an_artifact():
    pdf = _pdf(f'<p><img src="{PIXEL}" alt="" style="width:8px">Should Have</p>')

    _, elements = _structure(pdf)
    assert not [element for element in elements if element["/S"] == "/Figure"]
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert len(document[0].get_image_info()) == 1, "The image is still drawn"
        assert b"/Artifact" in document[0].read_contents()


def test_an_image_without_alt_is_named_by_its_title():
    pdf = _pdf(f'<p><img src="{PIXEL}" title="Diagram" style="width:8px"></p>')

    _, elements = _structure(pdf)
    assert [str(element["/Alt"]) for element in elements if element["/S"] == "/Figure"] == ["Diagram"]


def test_an_image_keeps_its_alt():
    pdf = _pdf(f'<p><img src="{PIXEL}" alt="Logo" title="Diagram" style="width:8px"></p>')

    _, elements = _structure(pdf)
    assert [str(element["/Alt"]) for element in elements if element["/S"] == "/Figure"] == ["Logo"]


@pytest.mark.parametrize("pdf_variant", [None, "pdf/a-2b"])
def test_an_untagged_pdf_is_drawn_as_before(pdf_variant):
    pdf = _pdf(f'<p><a href="https://example.com"><img src="{PIXEL}" alt="" style="width:8px"><span>Text</span></a></p>', pdf_variant)

    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert "/StructTreeRoot" not in reader.trailer["/Root"]
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert len(document[0].get_image_info()) == 1
        assert b"/Artifact" not in document[0].read_contents()


def test_a_link_annotation_without_a_link_above_stays():
    class Element(dict):
        def __init__(self, number: int, **entries: object) -> None:
            super().__init__(entries)
            self.number = number

        @property
        def reference(self) -> bytes:
            return f"{self.number} 0 R".encode()

    class Pdf:
        def __init__(self) -> None:
            self.objects: list[object] = [None]

        def add(self, element: Element) -> Element:
            self.objects.append(element)
            return element

    pdf = Pdf()
    document = pdf.add(Element(1, S="/Document"))
    span = pdf.add(Element(2, S="/Span", P=document.reference, K=[]))
    tree = pdf.add(Element(3, Nums=[1, span.reference]))
    root = pdf.add(Element(4, ParentTree=tree.reference))
    pdf.catalog = {"StructTreeRoot": root.reference}

    assert weasyprint_tagging_patch.move_annotations_to_links(pdf, 1) == 0
    assert tree["Nums"][1] == span.reference


def test_is_decorative():
    class Box(weasyprint_tagging_patch.weasyprint_boxes.ReplacedBox):
        def __init__(self, element: object) -> None:
            self.element = element

    class Element(dict):
        tag = "img"

    assert is_decorative(Box(Element(alt="")))
    assert not is_decorative(Box(Element(alt="Logo")))
    assert not is_decorative(Box(Element()))
    assert not is_decorative(Box(None))
    assert not is_decorative(object())


def test_patch_is_idempotent():
    assert apply_tagging_patch() is False
    assert is_applied()


def test_missing_module_degrades_to_none():
    assert weasyprint_tagging_patch._module("weasyprint.no_such_module") is None


def test_patch_skips_when_an_internal_is_missing(monkeypatch):
    monkeypatch.setattr(weasyprint_tagging_patch, "is_applied", lambda: False)
    monkeypatch.delattr(weasyprint_tagging_patch.weasyprint_tags, "_build_box_tree")
    marked = weasyprint_tagging_patch.weasyprint_stream.Stream.marked

    assert apply_tagging_patch() is False
    assert weasyprint_tagging_patch.weasyprint_stream.Stream.marked is marked, "Nothing is patched when one internal is missing"
