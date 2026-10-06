"""Tag links and images of a tagged PDF the way PDF/UA requires.

Background
----------
WeasyPrint's structure tree breaks two rules of PDF/UA-1 on ordinary HTML:

1. A link holding other elements, ``<a><span>1</span><span>Introduction</span></a>``,
   gets one link annotation per box inside it, and each annotation is put under the
   structure element of its box, a ``Span`` or a ``Figure``. PDF/UA requires it under
   the ``Link`` element (ISO 14289-1, 7.18.5; ISO 32000-1, 14.8.4.4.2).
2. An image whose ``alt`` is empty is decorative in HTML, yet it becomes a ``Figure``
   without an alternative text, which PDF/UA forbids (ISO 14289-1, 7.3). Such an
   image belongs in an artifact. An image with no ``alt`` but a ``title`` gets no
   alternative text either, though HTML names the image by its title then.

PDF/UA-2, built on PDF 2.0, adds three rules WeasyPrint breaks on ordinary HTML:

3. A list with markers needs a ``ListNumbering`` attribute on its ``L`` element
   (ISO 14289-2, 8.2.5.25).
4. A ``Span`` or a ``Link`` may not stand straight in a grouping element, a ``Div``
   or the ``Document``; WeasyPrint puts the text of a block ``div`` there.
5. A link to a place in the document needs a structure destination, the element it
   leads to (ISO 14289-2, 8.8); WeasyPrint writes a named destination only.

Fix
---
In a tagged PDF:

- each link annotation which is not under a ``Link`` element is moved under the
  nearest ``Link`` above it, and the parent tree follows;
- an image with an empty ``alt`` is drawn as an artifact and has no element in the
  structure tree; a link annotation of its own is moved under its ``Link`` as above;
- an image with no ``alt`` takes its ``title`` as its alternative text;
- the ``L`` element of a list states its ``ListNumbering``, from its ``list-style-type``;
- a ``TH`` element states its ``Scope``, so the headers of a cell stay certain when a merge makes the IDs WeasyPrint
  links them by, numbers of objects, ambiguous (PDF/UA-1, 7.5);
- a ``Link`` standing straight in another ``Link``, as WeasyPrint makes of a link pseudo element, as the page number of
  a table of contents, is merged into it, which ISO 32005 asks of PDF/UA-2.

In a tagged PDF 2.0, as PDF/UA-2 writes:

- a run of inline elements standing straight in a grouping element is wrapped in a
  ``P``, the paragraph its text makes;
- a link to a place in the document goes there by a ``GoTo`` action which keeps the
  named destination and adds the structure destination of the element holding the
  anchor.

The page does not change. An untagged PDF is left alone.

This is a temporary shim. ``apply_tagging_patch`` is idempotent and, if a future
WeasyPrint no longer exposes the patched internals, degrades to a no-op without ever
breaking PDF generation: it patches all of them or none, since drawing an image as an
artifact without leaving it out of the tree would fail WeasyPrint's own checks. Remove
it once WeasyPrint tags links, images, lists and destinations itself.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
from typing import TYPE_CHECKING, Any

import pydyf  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_link_and_image_tagging_patch"

# The ListNumbering of a list, by its list-style-type (ISO 32000-2, Table 380)
LIST_NUMBERING = {
    "disc": "Disc",
    "circle": "Circle",
    "square": "Square",
    "decimal": "Decimal",
    "decimal-leading-zero": "Decimal",
    "lower-roman": "LowerRoman",
    "upper-roman": "UpperRoman",
    "lower-alpha": "LowerAlpha",
    "lower-latin": "LowerAlpha",
    "upper-alpha": "UpperAlpha",
    "upper-latin": "UpperAlpha",
}

# Grouping elements, which hold blocks, and through which PDF 2.0 sees the one above (ISO 32000-2, 14.8.4.4)
GROUPING = frozenset({"/Document", "/Part", "/Art", "/Sect", "/Div", "/NonStruct", "/BlockQuote"})

# Inline elements, which a paragraph holds; a NonStruct is inline when it holds nothing else
INLINE = frozenset({"/Span", "/Link", "/Annot", "/Em", "/Strong", "/Code", "/Sub", "/Quote", "/Reference", "/Note"})

# The attributes of the PDF under which the anchors and the bookmarks of a conversion map to their elements
_ANCHORS = "_tagging_patch_anchors"
_BOOKMARKS = "_tagging_patch_bookmarks"
# The attribute of the PDF which holds the version it is written in, set before WeasyPrint builds its tree
_VERSION = "_tagging_patch_version"

# The ListNumbering values only PDF 2.0 knows; PDF 1.7 names an arbitrary label by None (ISO 32000-1, Table 347)
PDF_2_LIST_NUMBERING = frozenset({"Ordered", "Unordered"})


def _module(name: str) -> Any | None:
    """Import a private WeasyPrint module, or return ``None``.

    These modules are internal to WeasyPrint. A future WeasyPrint that moves or drops
    one must not stop the service from starting.
    """
    try:
        return importlib.import_module(name)
    except ImportError:
        logger.warning("WeasyPrint module %r not found; tagging patch degraded", name, exc_info=True)
        return None


weasyprint_pdf = _module("weasyprint.pdf")
weasyprint_tags = _module("weasyprint.pdf.tags")
weasyprint_stream = _module("weasyprint.pdf.stream")
weasyprint_boxes = _module("weasyprint.formatting_structure.boxes")


def _image(box: Any) -> Any | None:
    """The ``img`` element a replaced box draws, or ``None`` for any other box."""
    # An absolutely or fixed positioned box reaches the tree builder in an AbsolutePlaceholder
    box = getattr(box, "_box", box)
    if weasyprint_boxes is None or not isinstance(box, weasyprint_boxes.ReplacedBox):
        return None
    element = getattr(box, "element", None)
    return element if element is not None and element.tag == "img" else None


def is_decorative(box: Any) -> bool:
    """Whether a box draws an image which HTML calls decorative, by an empty ``alt``."""
    image = _image(box)
    return image is not None and image.get("alt") == ""


def _number(reference: Any) -> int:
    """The object number of a pydyf reference, as ``b"12 0 R"``."""
    return int(bytes(reference).split()[0])


def _with_decorative_artifacts(marked: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap Stream.marked so a decorative image is drawn as an artifact, not as a Figure."""

    @contextlib.contextmanager
    def wrapper(stream: Any, box: Any, tag: str) -> Iterator[None]:
        if tag == "Figure" and is_decorative(box):
            with stream.artifact():
                yield
        else:
            with marked(stream, box, tag):
                yield

    setattr(wrapper, _PATCH_FLAG, True)
    return wrapper


def _with_image_rules(build_box_tree: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap _build_box_tree to leave decorative images out and name an image by its title."""

    def wrapper(box: Any, parent: Any, pdf: Any, page_number: int, nums: Any, annotations: list[Any], tags: Any) -> Iterator[Any]:
        if is_decorative(box):
            # Drawn as an artifact, so it has no marked content to map. Its link annotation
            # still needs a place in the tree: under the parent, until it moves to its Link.
            annotation = getattr(box, "link_annotation", None)
            if annotation is not None:
                reference = pydyf.Dictionary({"Type": "/OBJR", "Obj": annotation.reference, "Pg": pdf.page_references[page_number]})
                pdf.add_object(reference)
                parent["K"].append(reference.reference)
                annotations.append((parent.reference, annotation))
            return
        image = _image(box)
        if image is not None and image.get("alt") is None and image.get("title"):
            image.set("alt", image.get("title"))
        own = _has_own_element(box)
        first: Any = None
        for element in build_box_tree(box, parent, pdf, page_number, nums, annotations, tags):
            if first is None:
                first = element
                if own:
                    set_list_numbering(box, element, getattr(pdf, _VERSION, None))
                    set_header_scope(box, element)
            yield element
        _record_anchor(box, first if own else None, parent, pdf)
        _record_bookmark(box, first if own else None, parent, pdf, page_number)

    setattr(wrapper, _PATCH_FLAG, True)
    return wrapper


def _move_object_reference(pdf: Any, holder: Any, link: Any, key: int) -> None:
    """Move the object reference of the annotation under the given parent tree key from its holder to the link."""
    for kid in holder["K"][:]:
        if isinstance(kid, int):
            continue
        kid_object = pdf.objects[_number(kid)]
        if isinstance(kid_object, pydyf.Dictionary) and kid_object.get("Type") == "/OBJR" and pdf.objects[_number(kid_object["Obj"])].get("StructParent") == key:
            holder["K"].remove(kid)
            link["K"].append(kid)


def _has_own_element(box: Any) -> bool:
    """Whether WeasyPrint gives a box an element of its own, not to the html, the body or a page."""
    if weasyprint_boxes is not None and isinstance(box, weasyprint_boxes.PageBox):
        return False
    return getattr(box, "element_tag", None) not in ("html", "body")


def set_list_numbering(box: Any, element: Any, pdf_version: Any = None) -> None:
    """State the ListNumbering of the L element of a list, by its list-style-type, in the values its PDF version knows."""
    if getattr(box, "element_tag", None) not in ("ul", "ol") or element.get("S") != "/L":
        return
    style = box.style["list_style_type"]
    if style == "none":
        numbering = "None"
    elif isinstance(style, str) and style in LIST_NUMBERING:
        numbering = LIST_NUMBERING[style]
    else:
        # A string or a counter style of its own: its kind is all a list states
        numbering = "Ordered" if box.element_tag == "ol" else "Unordered"
    if numbering in PDF_2_LIST_NUMBERING and not _is_pdf_2(pdf_version):
        numbering = "None"
    element["A"] = pydyf.Dictionary({"O": "/List", "ListNumbering": f"/{numbering}"})


def set_header_scope(box: Any, element: Any) -> None:
    """State the Scope of a TH element: Row where its th says scope="row", Column otherwise, as WeasyPrint reads it.

    WeasyPrint links the cells to their headers by IDs made of the number of the table object, which two merged
    documents can share, so after a merge the headers of a cell are no longer certain without a Scope (PDF/UA-1, 7.5).
    """
    if getattr(box, "element_tag", None) != "th" or element.get("S") != "/TH":
        return
    scope = "Row" if box.element.get("scope") == "row" else "Column"
    attributes = element.get("A")
    if not isinstance(attributes, pydyf.Dictionary):
        attributes = pydyf.Dictionary({"O": "/Table"})
        element["A"] = attributes
    attributes["Scope"] = f"/{scope}"


def _is_pdf_2(pdf_version: Any) -> bool:
    """Whether a PDF is written in version 2.0 or later; cast for bytes and None, as WeasyPrint compares it."""
    return str(pdf_version) >= "2.0"


def _record_anchor(box: Any, element: Any, parent: Any, pdf: Any) -> None:
    """Remember the element an anchor of the box leads to: its own, or its parent when it holds nothing."""
    anchor = box.style["anchor"] if hasattr(box, "style") else None
    if not anchor:
        return
    anchors = getattr(pdf, _ANCHORS, None)
    if anchors is None:
        anchors = {}
        setattr(pdf, _ANCHORS, anchors)
    target = element if element is not None and element.get("K") else parent
    anchors.setdefault(anchor, target)


def _record_bookmark(box: Any, element: Any, parent: Any, pdf: Any, page_number: int) -> None:
    """Remember the element of a box which makes a bookmark, by its page and its label, as WeasyPrint makes them."""
    label = getattr(box, "bookmark_label", None)
    if not label or box.style["bookmark_level"] == "none":
        return
    bookmarks = getattr(pdf, _BOOKMARKS, None)
    if bookmarks is None:
        bookmarks = {}
        setattr(pdf, _BOOKMARKS, bookmarks)
    bookmarks.setdefault((page_number, label), []).append(element if element is not None else parent)


def _kids(element: Any) -> list[Any]:
    kids = element.get("K")
    if kids is None:
        return []
    return list(kids) if isinstance(kids, (list, pydyf.Array)) else [kids]


def _is_inline(pdf: Any, kid: Any) -> bool:
    """Whether a kid is inline: an inline element, or a NonStruct holding inline elements only."""
    if isinstance(kid, int):
        return False
    element = pdf.objects[_number(kid)]
    if not isinstance(element, pydyf.Dictionary) or "S" not in element:
        return False
    if element["S"] in INLINE:
        return True
    if element["S"] != "/NonStruct":
        return False
    kids = _kids(element)
    return bool(kids) and all(_is_inline(pdf, grandkid) for grandkid in kids)


def wrap_inline_runs(pdf: Any, element: Any) -> int:
    """Wrap each run of inline kids standing straight in a grouping element in a P, below the element.

    Returns how many paragraphs it made.
    """
    made = 0
    if element.get("S") in GROUPING:
        kept = pydyf.Array()
        run: list[Any] = []

        def close_run() -> None:
            nonlocal made
            if not run:
                return
            first = pdf.objects[_number(run[0])]
            paragraph = pydyf.Dictionary({"Type": "/StructElem", "S": "/P", "K": pydyf.Array(run), "P": element.reference})
            if "Pg" in first:
                paragraph["Pg"] = first["Pg"]
            pdf.add_object(paragraph)
            for kid in run:
                pdf.objects[_number(kid)]["P"] = paragraph.reference
            kept.append(paragraph.reference)
            run.clear()
            made += 1

        for kid in _kids(element):
            if _is_inline(pdf, kid):
                run.append(kid)
            else:
                close_run()
                kept.append(kid)
        close_run()
        if made:
            element["K"] = kept
    for kid in _kids(element):
        # The text of an inline element is a paragraph's already, so it is not wrapped again
        if not isinstance(kid, int) and not _is_inline(pdf, kid):
            child = pdf.objects[_number(kid)]
            if isinstance(child, pydyf.Dictionary) and "S" in child:
                made += wrap_inline_runs(pdf, child)
    return made


def _named_destinations(pdf: Any) -> dict[str, Any]:
    """The named destinations of the document, by name."""
    names = pdf.catalog.get("Names")
    if names is None or "Dests" not in names:
        return {}
    dests = names["Dests"]
    dests = pdf.objects[_number(dests)] if isinstance(dests, bytes) else dests
    entries = dests.get("Names", [])
    return {_name(entries[index]): entries[index + 1] for index in range(0, len(entries), 2)}


def _name(value: Any) -> str:
    """The text of a pydyf string, as a destination name is written."""
    return str(value.string if hasattr(value, "string") else value)


def add_structure_destinations(pdf: Any, page_count: int) -> int:
    """Lead each link to a place in the document by a GoTo action with a structure destination.

    Returns how many links it changed.
    """
    anchors: dict[str, Any] = getattr(pdf, _ANCHORS, {})
    destinations = _named_destinations(pdf)
    root = pdf.objects[_number(pdf.catalog["StructTreeRoot"])]
    nums = pdf.objects[_number(root["ParentTree"])]["Nums"]
    changed = 0
    for index in range(0, len(nums), 2):
        if nums[index] < page_count:
            continue
        holder = pdf.objects[_number(nums[index + 1])]
        for kid in _kids(holder):
            if isinstance(kid, int):
                continue
            reference = pdf.objects[_number(kid)]
            if not isinstance(reference, pydyf.Dictionary) or reference.get("Type") != "/OBJR":
                continue
            annotation = pdf.objects[_number(reference["Obj"])]
            if "Dest" not in annotation:
                continue
            name = _name(annotation["Dest"])
            target, destination = anchors.get(name), destinations.get(name)
            if target is None or destination is None:
                continue
            annotation["A"] = pydyf.Dictionary(
                {
                    "Type": "/Action",
                    "S": "/GoTo",
                    "D": annotation["Dest"],
                    "SD": pydyf.Array([target.reference, *list(destination)[1:]]),
                }
            )
            del annotation["Dest"]
            changed += 1
    return changed


def _outlines(pdf: Any, first: Any) -> Iterator[Any]:
    """Every outline item from the first one given on, each before its children."""
    item_reference = first
    while item_reference is not None:
        item = pdf.objects[_number(item_reference)]
        yield item
        if "First" in item:
            yield from _outlines(pdf, item["First"])
        item_reference = item.get("Next")


def add_bookmark_structure_destinations(pdf: Any) -> int:
    """Lead each bookmark to its heading by a GoTo action with a structure destination.

    Returns how many bookmarks it changed.
    """
    bookmarks: dict[tuple[int, str], list[Any]] = getattr(pdf, _BOOKMARKS, {})
    outlines = pdf.catalog.get("Outlines")
    if not bookmarks or outlines is None:
        return 0
    root = pdf.objects[_number(outlines)]
    pages = [bytes(reference) for reference in pdf.page_references]
    changed = 0
    for item in _outlines(pdf, root.get("First")):
        destination = item.get("Dest")
        if destination is None or bytes(destination[0]) not in pages:
            continue
        targets = bookmarks.get((pages.index(bytes(destination[0])), _name(item["Title"])))
        if not targets:
            continue
        item["A"] = pydyf.Dictionary({"Type": "/Action", "S": "/GoTo", "D": destination, "SD": pydyf.Array([targets.pop(0).reference, *list(destination)[1:]])})
        del item["Dest"]
        changed += 1
    return changed


def merge_nested_links(pdf: Any) -> int:
    """Merge each Link element standing straight in another Link into that one; returns how many it merged.

    WeasyPrint makes a Link of a link and of each of its pseudo elements, as the page number of an entry of a table of
    contents, so a Link stands in a Link, which ISO 32005 forbids. The inner one hands its content, marked content,
    object references and elements, to the outer one, and the parent tree follows.
    """
    root = pdf.objects[_number(pdf.catalog["StructTreeRoot"])]
    replaced: dict[bytes, Any] = {}
    pending = [pdf.objects[_number(kid)] for kid in _kids(root) if not isinstance(kid, int)]
    while pending:
        element = pending.pop()
        if not isinstance(element, pydyf.Dictionary) or "S" not in element:
            continue
        if element["S"] == "/Link":
            _absorb_links(pdf, element, replaced)
        pending.extend(pdf.objects[_number(kid)] for kid in _kids(element) if not isinstance(kid, int))
    if replaced:
        _repoint_parent_tree(pdf, root, replaced)
    return len(replaced)


def _absorb_links(pdf: Any, link: Any, replaced: dict[bytes, Any]) -> None:
    """Splice the content of the Link elements among the kids of a Link into it, in their place, until none is left."""
    absorbed = True
    while absorbed:
        absorbed = False
        kept = pydyf.Array()
        for kid in _kids(link):
            inner = None if isinstance(kid, int) else pdf.objects[_number(kid)]
            if isinstance(inner, pydyf.Dictionary) and inner.get("S") == "/Link":
                kept.extend(_moved_content(pdf, inner, link))
                replaced[bytes(inner.reference)] = link
                absorbed = True
            else:
                kept.append(kid)
        link["K"] = kept


def _moved_content(pdf: Any, inner: Any, link: Any) -> list[Any]:
    """The content of an inner Link as the outer one holds it: marked content of another page as a reference to it."""
    moved: list[Any] = []
    other_page = "Pg" in inner and inner.get("Pg") != link.get("Pg")
    for kid in _kids(inner):
        if isinstance(kid, int):
            if other_page:
                reference = pydyf.Dictionary({"Type": "/MCR", "Pg": inner["Pg"], "MCID": kid})
                pdf.add_object(reference)
                moved.append(reference.reference)
            else:
                moved.append(kid)
            continue
        child = pdf.objects[_number(kid)]
        if isinstance(child, pydyf.Dictionary) and "S" in child:
            # Its marked content is on the page of the inner Link, which it took as its own where it names none
            if other_page and "Pg" not in child:
                child["Pg"] = inner["Pg"]
            child["P"] = link.reference
        moved.append(kid)
    return moved


def _repoint_parent_tree(pdf: Any, root: Any, replaced: dict[bytes, Any]) -> None:
    """Make the parent tree name the outer Link wherever it named a Link merged into it."""

    def outer(reference: Any) -> Any:
        link = replaced.get(bytes(reference)) if isinstance(reference, (bytes, bytearray)) else None
        while link is not None and bytes(link.reference) in replaced:
            link = replaced[bytes(link.reference)]
        return link.reference if link is not None else reference

    nums = pdf.objects[_number(root["ParentTree"])]["Nums"]
    for index in range(1, len(nums), 2):
        value = nums[index]
        if isinstance(value, pydyf.Array):
            for position, reference in enumerate(value):
                value[position] = outer(reference)
        else:
            nums[index] = outer(value)


def move_annotations_to_links(pdf: Any, page_count: int) -> int:
    """Move each link annotation which is not under a Link element under the nearest one above it.

    WeasyPrint maps the keys from ``page_count`` on in the parent tree to the elements
    holding the annotations. Returns how many annotations moved.
    """
    root = pdf.objects[_number(pdf.catalog["StructTreeRoot"])]
    nums = pdf.objects[_number(root["ParentTree"])]["Nums"]
    moved = 0
    for index in range(0, len(nums), 2):
        key = nums[index]
        if key < page_count:
            continue
        holder = pdf.objects[_number(nums[index + 1])]
        link = holder
        while link["S"] != "/Link" and "P" in link and link["S"] != "/Document":
            link = pdf.objects[_number(link["P"])]
        if link is holder or link["S"] != "/Link":
            continue
        _move_object_reference(pdf, holder, link, key)
        nums[index + 1] = link.reference
        moved += 1
    return moved


def _with_links_moved(add_tags: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap add_tags so the link annotations end under their Link elements."""

    def wrapper(pdf: Any, document: Any, pdf_version: Any, *args: Any, **kwargs: Any) -> Any:
        setattr(pdf, _VERSION, pdf_version)
        result = add_tags(pdf, document, pdf_version, *args, **kwargs)
        move_annotations_to_links(pdf, len(document.pages))
        merge_nested_links(pdf)
        if _is_pdf_2(pdf_version):
            root = pdf.objects[_number(pdf.catalog["StructTreeRoot"])]
            for kid in _kids(root):
                wrap_inline_runs(pdf, pdf.objects[_number(kid)])
            add_structure_destinations(pdf, len(document.pages))
            add_bookmark_structure_destinations(pdf)
        return result

    setattr(wrapper, _PATCH_FLAG, True)
    return wrapper


def apply_tagging_patch() -> bool:
    """Monkey-patch WeasyPrint so links and images are tagged as PDF/UA requires.

    Returns ``True`` when the patch is applied, ``False`` when it was already applied or
    the WeasyPrint internals could not be located.
    """
    if None in (weasyprint_pdf, weasyprint_tags, weasyprint_stream, weasyprint_boxes) or is_applied():
        return False

    stream_class = getattr(weasyprint_stream, "Stream", None)
    targets: dict[str, Any] = {
        "Stream.marked": getattr(stream_class, "marked", None),
        "tags._build_box_tree": getattr(weasyprint_tags, "_build_box_tree", None),
        "tags.add_tags": getattr(weasyprint_tags, "add_tags", None),
        "pdf.add_tags": getattr(weasyprint_pdf, "add_tags", None),
        "boxes.ReplacedBox": getattr(weasyprint_boxes, "ReplacedBox", None),
        "boxes.PageBox": getattr(weasyprint_boxes, "PageBox", None),
    }
    missing = [name for name, target in targets.items() if target is None]
    if missing:
        logger.warning("WeasyPrint internals not found (%s); tagging patch skipped", ", ".join(missing))
        return False

    add_tags = _with_links_moved(targets["tags.add_tags"])
    setattr(stream_class, "marked", _with_decorative_artifacts(targets["Stream.marked"]))  # noqa: B010 - a private method of WeasyPrint
    setattr(weasyprint_tags, "_build_box_tree", _with_image_rules(targets["tags._build_box_tree"]))  # noqa: B010 - a private function of WeasyPrint
    setattr(weasyprint_tags, "add_tags", add_tags)  # noqa: B010 - replaced in both modules which bind it
    setattr(weasyprint_pdf, "add_tags", add_tags)  # noqa: B010 - replaced in both modules which bind it

    logger.info("Applied WeasyPrint tagging patch (link annotations under their Link, decorative images as artifacts)")
    return True


def is_applied() -> bool:
    """Return whether the tagging patch is installed."""
    stream_class = getattr(weasyprint_stream, "Stream", None)
    targets = (
        getattr(stream_class, "marked", None),
        getattr(weasyprint_tags, "_build_box_tree", None),
        getattr(weasyprint_tags, "add_tags", None),
        getattr(weasyprint_pdf, "add_tags", None),
    )
    return all(getattr(target, _PATCH_FLAG, False) for target in targets)
