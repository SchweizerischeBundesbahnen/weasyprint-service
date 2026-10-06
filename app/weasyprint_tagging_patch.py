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

Fix
---
In a tagged PDF:

- each link annotation which is not under a ``Link`` element is moved under the
  nearest ``Link`` above it, and the parent tree follows;
- an image with an empty ``alt`` is drawn as an artifact and has no element in the
  structure tree; a link annotation of its own is moved under its ``Link`` as above;
- an image with no ``alt`` takes its ``title`` as its alternative text.

The page does not change. An untagged PDF is left alone.

This is a temporary shim. ``apply_tagging_patch`` is idempotent and, if a future
WeasyPrint no longer exposes the patched internals, degrades to a no-op without ever
breaking PDF generation: it patches all of them or none, since drawing an image as an
artifact without leaving it out of the tree would fail WeasyPrint's own checks. Remove
it once WeasyPrint tags links and decorative images itself.
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
        yield from build_box_tree(box, parent, pdf, page_number, nums, annotations, tags)

    setattr(wrapper, _PATCH_FLAG, True)
    return wrapper


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
        for kid in list(holder["K"]):
            if isinstance(kid, int):
                continue
            kid_object = pdf.objects[_number(kid)]
            if isinstance(kid_object, pydyf.Dictionary) and kid_object.get("Type") == "/OBJR" and pdf.objects[_number(kid_object["Obj"])].get("StructParent") == key:
                holder["K"].remove(kid)
                link["K"].append(kid)
        nums[index + 1] = link.reference
        moved += 1
    return moved


def _with_links_moved(add_tags: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap add_tags so the link annotations end under their Link elements."""

    def wrapper(pdf: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        result = add_tags(pdf, document, *args, **kwargs)
        move_annotations_to_links(pdf, len(document.pages))
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
