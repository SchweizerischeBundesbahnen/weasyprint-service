from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Iterator, List, Optional

import contextlib
import pypdf as PyPDF
import pymupdf
from PIL import Image, ImageChops


def pdf_bytes_to_png_pages(
    pdf_bytes: bytes,
    *,
    zoom: Optional[float] = None,
    matrix: Optional[pymupdf.Matrix] = None,
    alpha: bool = False,
) -> List[bytes]:
    """
    Convert all pages of a PDF (given as bytes) to PNG images (bytes), in order.

    Args:
        pdf_bytes: The PDF document content in bytes.
        zoom: Optional uniform zoom factor for both axes. Ignored if `matrix` is provided.
        matrix: Optional pymupdf.Matrix to control rasterization scale/transform.
        alpha: Whether to include alpha channel in the output PNGs.

    Returns:
        List of PNG bytes, one per page, in page order (0..n-1).
    """
    if matrix is None:
        if zoom is None:
            matrix = pymupdf.Matrix(1.0, 1.0)
        else:
            matrix = pymupdf.Matrix(zoom, zoom)

    png_pages: List[bytes] = []
    # Use context manager to ensure resources are freed
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_number in range(doc.page_count):
            page = doc.load_page(page_number)
            pix = page.get_pixmap(matrix=matrix, alpha=alpha)
            png_pages.append(pix.tobytes("png"))
    return png_pages


def assert_png_pages_equal_to_refs(
    produced_pages: List[bytes],
    ref_base: Path,
    *,
    update_env_var: str = "UPDATE_EXPECTED_REFS",
    pdf_bytes: bytes | None = None,
) -> None:
    """
    Compare a list of produced PNG page bytes with reference images on disk.

    Reference naming convention:
      - use ref_base with suffix .page-<index>.png for each page,
        where index starts at 0. Example: svg-image-ref.page-0.png, svg-image-ref.page-1.png
        For a single-page document, expect only svg-image-ref.page-0.png.

    If a reference image is missing and the environment variable specified by
    update_env_var is set to "1", the reference(s) will be generated and the caller
    should skip the test with an explanatory message.

    Args:
        produced_pages: List of PNG bytes for each page
        ref_base: Base path for reference PNG files
        update_env_var: Environment variable name to check for update mode
        pdf_bytes: Optional PDF bytes to save alongside PNG references when updating
    """
    n_pages = len(produced_pages)

    def page_ref_path(i: int) -> Path:
        # Create path like: /path/to/base-name.page-0.png
        stem = ref_base.stem  # e.g., "html-with-svg-and-png-in-tables"
        suffix = ref_base.suffix  # e.g., ".png"
        parent = ref_base.parent  # e.g., "tests/test-data/expected"
        return parent / f"{stem}.page-{i}{suffix}"

    # Verify references exist or generate them
    missing = []
    for i in range(n_pages):
        p = page_ref_path(i)
        if not p.exists():
            missing.append(p)

    if missing:
        if os.environ.get(update_env_var, "0") == "1":
            ref_base.parent.mkdir(parents=True, exist_ok=True)
            # Write all produced pages into reference files
            for i, png in enumerate(produced_pages):
                page_ref = page_ref_path(i)
                page_ref.write_bytes(png)
            # Save PDF file if provided
            if pdf_bytes is not None:
                pdf_ref_path = ref_base.with_suffix(".pdf")
                pdf_ref_path.write_bytes(pdf_bytes)
            raise ReferenceGenerated(str(missing))
        else:
            raise ReferenceMissing(f"Missing reference images: {', '.join(map(str, missing))}. Set {update_env_var}=1 to generate references.")

    # Compare each page
    for i, png in enumerate(produced_pages):
        produced_img = Image.open(BytesIO(png))
        ref_img = Image.open(page_ref_path(i))
        assert produced_img.mode == ref_img.mode and produced_img.size == ref_img.size
        assert ImageChops.difference(produced_img, ref_img).getbbox() is None


class ReferenceMissing(AssertionError):
    pass


class ReferenceGenerated(RuntimeError):
    pass


def get_pdf_variant_from_metadata(pdf_reader: PyPDF.PdfReader) -> str:
    if pdf_reader.xmp_metadata and pdf_reader.xmp_metadata.rdf_root:
        for rdf_node in pdf_reader.xmp_metadata.rdf_root.childNodes:
            part = rdf_node.attributes.get("pdfaid:part")
            conformance = rdf_node.attributes.get("pdfaid:conformance")
            if part and conformance:
                return f"pdf/a-{part.value}{conformance.value}".lower()
    return ""


def extract_all_attachments(reader: PyPDF.PdfReader):
    DictObj = PyPDF.generic.DictionaryObject
    IndObj  = PyPDF.generic.IndirectObject
    ArrObj  = PyPDF.generic.ArrayObject

    def _as_obj(x):
        return x.get_object() if isinstance(x, IndObj) else x

    def _yield_filespec(fs_obj, name_hint: str, source: str):
        fs = _as_obj(fs_obj)
        if not isinstance(fs, DictObj):
            return
        name = fs.get("/UF") or fs.get("/F") or name_hint or "unnamed"
        yield (str(name), source)

    def _walk_name_tree(node, source: str):
        node = _as_obj(node)
        if not isinstance(node, DictObj):
            return
        names = node.get("/Names")
        if isinstance(names, ArrObj):
            for i in range(0, len(names), 2):
                name = names[i]
                fs   = names[i + 1]
                yield from _yield_filespec(fs, str(name), source)
        kids = node.get("/Kids")
        if isinstance(kids, ArrObj):
            for kid in kids:
                yield from _walk_name_tree(kid, source)

    def _iter_af(holder, source: str):
        holder = _as_obj(holder)
        if not isinstance(holder, DictObj):
            return
        af = holder.get("/AF")
        if af is None:
            return
        items = af if isinstance(af, ArrObj) else [af]
        for item in items:
            yield from _yield_filespec(item, None, source)

    out: list[tuple[str, str]] = []
    catalog = reader.trailer["/Root"]

    # 1) NameTree
    with contextlib.suppress(Exception):
        names = catalog.get("/Names")
        if isinstance(names, DictObj):
            embedded = names.get("/EmbeddedFiles")
            if embedded is not None:
                out.extend(_walk_name_tree(embedded, "NamesTree"))

    # 2) AF of catalog
    out.extend(_iter_af(catalog, "AF:Catalog"))

    # 3) Pages
    for page_idx, page in enumerate(reader.pages):
        p = _as_obj(page)
        annots = p.get("/Annots")
        if isinstance(annots, ArrObj):
            for ann in annots:
                a = _as_obj(ann)
                if isinstance(a, DictObj) and a.get("/Subtype") == "/FileAttachment":
                    fs = a.get("/FS")
                    if fs is not None:
                        out.extend(_yield_filespec(fs, None, f"Annot:p{page_idx}"))
                out.extend(_iter_af(a, f"AF:Annot:p{page_idx}"))
        out.extend(_iter_af(p, f"AF:Page:{page_idx}"))

    return out
