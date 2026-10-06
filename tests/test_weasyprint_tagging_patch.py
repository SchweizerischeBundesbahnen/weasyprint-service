"""Regression test for the WeasyPrint patch tagging links and images as PDF/UA requires."""

import io

import pydyf
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


@pytest.mark.parametrize("position", ["absolute", "fixed"])
def test_a_positioned_decorative_image_is_an_artifact(position):
    pdf = _pdf(f'<p><img src="{PIXEL}" alt="" style="position:{position};top:0;left:0;width:8px">Should Have</p>')

    _, elements = _structure(pdf)
    assert not [element for element in elements if element["/S"] == "/Figure"]
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert len(document[0].get_image_info()) == 1, "The image is still drawn"


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


# ------------------------------------------------------------------ PDF/UA-2, written as PDF 2.0


def _element_of(reference: object) -> pypdf.generic.DictionaryObject:
    return reference.get_object() if hasattr(reference, "get_object") else reference


@pytest.mark.parametrize(
    ("list_html", "numbering"),
    [
        ("<ul><li>One</li></ul>", "/Disc"),
        ('<ul style="list-style-type:square"><li>One</li></ul>', "/Square"),
        ("<ol><li>One</li></ol>", "/Decimal"),
        ('<ol style="list-style-type:upper-roman"><li>One</li></ol>', "/UpperRoman"),
        ('<ol style="list-style-type:lower-latin"><li>One</li></ol>', "/LowerAlpha"),
        ("<ul style=\"list-style-type:'-'\"><li>One</li></ul>", "/Unordered"),
        ('<ol style="list-style-type:georgian"><li>One</li></ol>', "/Ordered"),
        ('<ul style="list-style-type:none"><li>One</li></ul>', "/None"),
    ],
)
def test_a_list_states_its_numbering(list_html, numbering):
    _, elements = _structure(_pdf(list_html, "pdf/ua-2"))

    lists = [element for element in elements if element["/S"] == "/L"]
    assert [str(element["/A"]["/ListNumbering"]) for element in lists] == [numbering]
    assert str(lists[0]["/A"]["/O"]) == "/List"


def test_the_text_of_a_div_is_a_paragraph_in_pdf_2():
    _, elements = _structure(_pdf("<div>Loose <b>bold</b> text<p>Paragraph</p>after</div>", "pdf/ua-2"))

    grouping = {"/Document", "/Div"}
    for element in elements:
        if element["/S"] in grouping:
            kids = element.get("/K")
            kids = kids if isinstance(kids, pypdf.generic.ArrayObject) else [kids]
            assert not [kid for kid in kids if hasattr(kid, "get_object") and _element_of(kid).get("/S") == "/Span"], "No Span stands straight in a grouping element"
    paragraphs = [element for element in elements if element["/S"] == "/P"]
    assert len(paragraphs) == 3, "The text before and after the paragraph make one paragraph each"
    for paragraph in paragraphs:
        assert _element_of(paragraph["/P"])["/S"] != "/P", "No paragraph stands in another"


def test_a_block_link_holds_no_paragraph_in_pdf_2():
    """PDF 2.0 forbids a P in a Link used as a non-grouping element; veraPDF accepts the Span of its div."""
    _, elements = _structure(_pdf('<a href="https://example.com" style="display:block"><div>Text</div></a><p><a href="https://example.com">inline</a></p>', "pdf/ua-2"))

    for link in (element for element in elements if element["/S"] == "/Link"):
        kids = link["/K"] if isinstance(link["/K"], pypdf.generic.ArrayObject) else [link["/K"]]
        below = [_element_of(kid) for kid in kids if isinstance(_element_of(kid), pypdf.generic.DictionaryObject)]
        while below:
            element = below.pop()
            assert element.get("/S") != "/P", "No paragraph is made inside a link"
            kids = element.get("/K")
            kids = kids if isinstance(kids, pypdf.generic.ArrayObject) else [kids]
            below.extend(_element_of(kid) for kid in kids if isinstance(_element_of(kid), pypdf.generic.DictionaryObject))


def test_the_text_of_a_div_stays_in_pdf_1_7():
    _, elements = _structure(_pdf("<div>Loose text</div>", "pdf/ua-1"))

    assert not [element for element in elements if element["/S"] == "/P"]


def test_a_link_to_a_place_in_the_document_has_a_structure_destination():
    pdf = _pdf('<h1 id="head">Head</h1><p><a href="#head">to the head</a> <a href="#item">to the item</a> <a href="https://example.com">out</a></p><div><a id="item"></a>Item</div>', "pdf/ua-2")

    reader, _ = _structure(pdf)
    targets = {}
    for annotation in _link_annotations(reader):
        assert "/Dest" not in annotation
        action = annotation["/A"]
        if action["/S"] == "/URI":
            continue
        assert action["/S"] == "/GoTo"
        targets[str(action["/D"])] = _element_of(action["/SD"][0])["/S"]
        assert str(action["/SD"][1]) == "/XYZ"
    assert targets == {"head": "/H1", "item": "/Div"}, "An empty anchor leads to the element around it"


def test_a_link_keeps_its_named_destination_in_pdf_1_7():
    reader, _ = _structure(_pdf('<h1 id="head">Head</h1><p><a href="#head">to the head</a></p>', "pdf/ua-1"))

    assert [str(annotation["/Dest"]) for annotation in _link_annotations(reader)] == ["head"]


def test_a_bookmark_has_a_structure_destination():
    reader, _ = _structure(_pdf("<h1>First</h1><p>Text</p><h2>Second</h2><h1>First</h1>", "pdf/ua-2"))

    items = []
    item = reader.trailer["/Root"]["/Outlines"]["/First"]
    stack = [item]
    while stack:
        node = stack.pop().get_object()
        items.append(node)
        if "/Next" in node:
            stack.append(node["/Next"])
        if "/First" in node:
            stack.append(node["/First"])
    assert len(items) == 3
    for node in items:
        assert "/Dest" not in node
        heading = _element_of(node["/A"]["/SD"][0])
        assert heading["/S"] in ("/H1", "/H2")
    assert len({id(_element_of(node["/A"]["/SD"][0])) for node in items}) == 3, "Two headings of one title lead to their own elements"


@pytest.mark.parametrize(
    ("list_html", "numbering"),
    [
        ("<ul><li>One</li></ul>", "/Disc"),
        ('<ol style="list-style-type:upper-roman"><li>One</li></ol>', "/UpperRoman"),
        ("<ul style=\"list-style-type:'-'\"><li>One</li></ul>", "/None"),
        ('<ol style="list-style-type:georgian"><li>One</li></ol>', "/None"),
    ],
)
def test_a_list_states_a_numbering_pdf_1_7_knows(list_html, numbering):
    _, elements = _structure(_pdf(list_html, "pdf/ua-1"))

    assert [str(element["/A"]["/ListNumbering"]) for element in elements if element["/S"] == "/L"] == [numbering]


def _destinations_pdf(anchors: dict, names: list) -> tuple[pydyf.PDF, pydyf.Dictionary]:
    """A PDF of one page whose one link goes to the named destination "target", with the anchors and the names given."""
    pdf = pydyf.PDF()
    pdf.add_page(pydyf.Dictionary({"Type": "/Page"}))
    annotation = pydyf.Dictionary({"Type": "/Annot", "Subtype": "/Link", "Dest": pydyf.String("target"), "StructParent": 1})
    pdf.add_object(annotation)
    reference = pydyf.Dictionary({"Type": "/OBJR", "Obj": annotation.reference})
    pdf.add_object(reference)
    link = pydyf.Dictionary({"Type": "/StructElem", "S": "/Link", "K": pydyf.Array([reference.reference])})
    pdf.add_object(link)
    tree = pydyf.Dictionary({"Nums": pydyf.Array([1, link.reference])})
    pdf.add_object(tree)
    root = pydyf.Dictionary({"Type": "/StructTreeRoot", "ParentTree": tree.reference})
    pdf.add_object(root)
    pdf.catalog["StructTreeRoot"] = root.reference
    pdf.catalog["Names"] = pydyf.Dictionary({"Dests": pydyf.Dictionary({"Names": pydyf.Array(names)})})
    setattr(pdf, "_tagging_patch_anchors", anchors)  # noqa: B010 - the attribute the patch reads
    return pdf, annotation


def test_a_link_with_a_known_target_gets_a_structure_destination():
    heading = pydyf.Dictionary({"Type": "/StructElem", "S": "/H1"})
    pdf, annotation = _destinations_pdf({}, [])
    pdf.add_object(heading)
    setattr(pdf, "_tagging_patch_anchors", {"target": heading})  # noqa: B010 - the attribute the patch reads
    pdf.catalog["Names"]["Dests"]["Names"] = pydyf.Array([pydyf.String("target"), pydyf.Array([pdf.page_references[0], "/XYZ", 0, 0, 0])])

    assert weasyprint_tagging_patch.add_structure_destinations(pdf, 1) == 1
    assert "Dest" not in annotation
    assert annotation["A"]["SD"][0] == heading.reference


def test_a_link_without_a_known_anchor_keeps_its_named_destination():
    pdf, annotation = _destinations_pdf({}, [pydyf.String("target"), pydyf.Array([b"1 0 R", "/XYZ", 0, 0, 0])])

    assert weasyprint_tagging_patch.add_structure_destinations(pdf, 1) == 0
    assert annotation["Dest"].string == "target"
    assert "A" not in annotation


def test_a_link_without_a_named_destination_keeps_it():
    heading = pydyf.Dictionary({"Type": "/StructElem", "S": "/H1"})
    pdf, annotation = _destinations_pdf({}, [])
    pdf.add_object(heading)
    setattr(pdf, "_tagging_patch_anchors", {"target": heading})  # noqa: B010 - the attribute the patch reads

    assert weasyprint_tagging_patch.add_structure_destinations(pdf, 1) == 0
    assert annotation["Dest"].string == "target"


def test_a_bookmark_without_a_known_heading_keeps_its_destination():
    pdf, _ = _destinations_pdf({}, [])
    destination = pydyf.Array([pdf.page_references[0], "/XYZ", 0, 0, 0])
    item = pydyf.Dictionary({"Title": pydyf.String("Unknown"), "Dest": destination})
    pdf.add_object(item)
    outlines = pydyf.Dictionary({"Type": "/Outlines", "First": item.reference})
    pdf.add_object(outlines)
    pdf.catalog["Outlines"] = outlines.reference
    heading = pydyf.Dictionary({"Type": "/StructElem", "S": "/H1"})
    pdf.add_object(heading)
    setattr(pdf, "_tagging_patch_bookmarks", {(0, "Known"): [heading]})  # noqa: B010 - the attribute the patch reads

    assert weasyprint_tagging_patch.add_bookmark_structure_destinations(pdf) == 0
    assert item["Dest"] is destination
