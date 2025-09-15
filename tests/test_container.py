import contextlib
import io
import logging
import time
from collections import Counter
from pathlib import Path
from typing import NamedTuple, Iterator

import docker
import pymupdf
import pypdf as PyPDF
import pytest
import requests
from docker.models.containers import Container
from PIL import Image, ImageChops


class TestParameters(NamedTuple):
    base_url: str
    flush_tmp_file_enabled: bool
    request_session: requests.Session
    container: Container
    # prevent pytest from collecting NamedTuple as a test
    __test__ = False


@pytest.fixture(scope="module")
def weasyprint_container():
    """
    Setup function for building and starting the weasyprint-service image.
    Runs once per module and is cleaned up after execution

    Yields:
        Container: Built docker container
    """
    client = docker.from_env()
    image, _ = client.images.build(path=".", tag="weasyprint_service", buildargs={"APP_IMAGE_VERSION": "1.0.0"})
    container = client.containers.run(
        image=image,
        detach=True,
        name="weasyprint_service",
        ports={"9080": 9080},
        init=True,  # Enable Docker's init process (equivalent to tini)
    )
    time.sleep(5)

    yield container

    container.stop()
    container.remove()


@pytest.fixture(scope="module")
def test_parameters(weasyprint_container: Container):
    """
    Setup function for test parameters and request session.
    Runs once per module and is cleaned up after execution.

    Args:
        weasyprint_container (Container): weasyprint-service docker container

    Yields:
        TestParameters: The setup test parameters
    """
    base_url = "http://localhost:9080"
    flush_tmp_file_enabled = False
    request_session = requests.Session()
    yield TestParameters(base_url, flush_tmp_file_enabled, request_session, weasyprint_container)
    request_session.close()


def test_container_no_error_logs(test_parameters: TestParameters) -> None:
    logs = test_parameters.container.logs()

    assert len(logs.splitlines()) == 7


def test_convert_simple_html(test_parameters: TestParameters) -> None:
    simple_html = "<html><body>My test body</body</html>"

    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=simple_html, print_error=True)
    assert response.status_code == 200
    flush_tmp_file("test_convert_simple_html.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)
    total_pages = len(pdf_reader.pages)
    assert total_pages == 1
    first_page = pdf_reader.pages[0].extract_text()
    assert "My test body" in first_page
    assert response.headers.get("Weasyprint-Version")
    assert response.headers.get("Python-Version")


def test_convert_complex_html(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/test-specification.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200
    flush_tmp_file("test_convert_complex_html.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)
    total_pages = len(pdf_reader.pages)
    assert total_pages == 4
    page = pdf_reader.pages[1].extract_text()
    assert "Test Specification" in page


def test_convert_complex_html_without_embedded_attachments(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/test-specification.html")
    response = __call_convert_html_with_attachments(
        base_url=test_parameters.base_url,
        request_session=test_parameters.request_session,
        data=html,
        print_error=True
    )
    assert response.status_code == 200
    flush_tmp_file("test_convert_complex_html.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)
    total_pages = len(pdf_reader.pages)
    assert total_pages == 4
    page = pdf_reader.pages[1].extract_text()
    assert "Test Specification" in page


def test_convert_complex_html_with_embedded_attachments(test_parameters: TestParameters) -> None:
    # Prepare HTML and two files to embed as attachments
    html = __load_test_html("tests/test-data/test-specification.html")

    file1_path = Path("tests/test-data/html-with-attachments/attachment1.pdf")
    file2_path = Path("tests/test-data/html-with-attachments/attachment2.pdf")

    file1_bytes = file1_path.read_bytes()
    file2_bytes = file2_path.read_bytes()

    files = [
        ("files", (file1_path.name, file1_bytes, "application/pdf")),
        ("files", (file2_path.name, file2_bytes, "application/pdf")),
    ]

    response = __call_convert_html_with_attachments(
        base_url=test_parameters.base_url,
        request_session=test_parameters.request_session,
        data=html,
        print_error=True,
        files=files,
    )

    assert response.status_code == 200
    flush_tmp_file("test_convert_complex_html_with_embedded_attachments.pdf", response.content, test_parameters.flush_tmp_file_enabled)

    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)

    # Basic PDF validation
    assert len(pdf_reader.pages) == 4
    page = pdf_reader.pages[1].extract_text()
    assert "Test Specification" in page

    # Validate attachments
    # Use high-level API if available in pypdf 6
    names = getattr(pdf_reader, "attachments", None)
    attachment_names = set(names.keys())

    assert file1_path.name in attachment_names
    assert file2_path.name in attachment_names


def test_convert_html_with_embedded_attachments(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/html-with-attachments.html")

    file1_path = Path("tests/test-data/html-with-attachments/attachment1.pdf")
    file2_path = Path("tests/test-data/html-with-attachments/attachment2.pdf")
    file3_path = Path("tests/test-data/html-with-attachments/attachment3.pdf")

    file1_bytes = file1_path.read_bytes()
    file2_bytes = file2_path.read_bytes()
    file3_bytes = file3_path.read_bytes()

    files = [
        ("files", (file1_path.name, file1_bytes, "application/pdf")),
        ("files", (file2_path.name, file2_bytes, "application/pdf")),
        ("files", (file3_path.name, file3_bytes, "application/pdf")),
    ]

    response = __call_convert_html_with_attachments(
        base_url=test_parameters.base_url,
        request_session=test_parameters.request_session,
        data=html,
        print_error=True,
        files=files,
    )

    assert response.status_code == 200
    flush_tmp_file("test_convert_html_with_embedded_attachments.pdf", response.content, test_parameters.flush_tmp_file_enabled)

    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)

    # Basic PDF validation
    assert len(pdf_reader.pages) == 1
    page = pdf_reader.pages[0].extract_text()
    assert "Lorem ipsum dolor sit amet, consectetur adipiscing elit." in page

    # Validate attachments
    attachments = __extract_all_attachments(pdf_reader)

    expected = [
        (file1_path.name, 'NamesTree'),
        (file2_path.name, 'NamesTree'),
        (file3_path.name, 'NamesTree'),
        (file1_path.name, 'Annot:p0'),
        (file2_path.name, 'Annot:p0'),
        (file1_path.name, 'Annot:p0'),
    ]
    assert Counter(attachments) == Counter(expected)


def test_convert_svg(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/svg-image.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200

    # Render first page to PNG
    doc = pymupdf.open(stream=response.content, filetype="pdf")
    page = doc.load_page(0)
    page_png_bytes = page.get_pixmap().tobytes("png")

    flush_tmp_file("test_convert_svg_image.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    flush_tmp_file("test_convert_svg_image.png", page_png_bytes, test_parameters.flush_tmp_file_enabled)

    produced_img = Image.open(io.BytesIO(page_png_bytes))
    ref_path = Path("tests/test-data/expected/svg-image-ref.png")

    if not ref_path.exists():
        import os
        if os.environ.get("UPDATE_EXPECTED_REFS", "0") == "1":
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_bytes(page_png_bytes)
            pdf_ref_path = ref_path.with_suffix(".pdf")
            pdf_ref_path.write_bytes(response.content)
            pytest.skip(
                f"Reference {ref_path} (and {pdf_ref_path}) was missing and has been generated. Re-run tests."
            )
        else:
            pytest.skip(
                f"Missing reference image {ref_path}. Set UPDATE_EXPECTED_REFS=1 to generate references (PNG and PDF), then commit them under tests/test-data/expected."
            )

    ref_image = Image.open(ref_path)
    assert produced_img.mode == ref_image.mode and produced_img.size == ref_image.size
    assert ImageChops.difference(produced_img, ref_image).getbbox() is None


def test_convert_svg_as_base64(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/svg-image-as-base64.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200

    # Render first page to PNG
    doc = pymupdf.open(stream=response.content, filetype="pdf")
    page = doc.load_page(0)
    page_png_bytes = page.get_pixmap().tobytes("png")

    flush_tmp_file("test_convert_svg_image_as_base64.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    flush_tmp_file("test_convert_svg_image_as_base64.png", page_png_bytes, test_parameters.flush_tmp_file_enabled)

    produced_img = Image.open(io.BytesIO(page_png_bytes))
    ref_path = Path("tests/test-data/expected/svg-image-as-base64-ref.png")

    if not ref_path.exists():
        import os
        if os.environ.get("UPDATE_EXPECTED_REFS", "0") == "1":
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_bytes(page_png_bytes)
            pdf_ref_path = ref_path.with_suffix(".pdf")
            pdf_ref_path.write_bytes(response.content)
            pytest.skip(
                f"Reference {ref_path} (and {pdf_ref_path}) was missing and has been generated. Re-run tests."
            )
        else:
            pytest.skip(
                f"Missing reference image {ref_path}. Set UPDATE_EXPECTED_REFS=1 to generate references (PNG and PDF), then commit them under tests/test-data/expected."
            )

    ref_image = Image.open(ref_path)
    assert produced_img.mode == ref_image.mode and produced_img.size == ref_image.size
    assert ImageChops.difference(produced_img, ref_image).getbbox() is None


@pytest.mark.parametrize("scale", [1.0, 2.0, 3.125, 6.25])
def test_convert_svg_with_scale_factor(scale: float, test_parameters: TestParameters) -> None:
    """
    Integration test: render svg-image.html with different scale_factor values and
    compare rasterized first page PNGs with reference images.

    If a reference image is missing and the environment variable UPDATE_EXPECTED_REFS=1
    is set, the test will generate the reference PNG into tests/test-data/expected and skip
    with an explanatory message.
    """
    html = __load_test_html("tests/test-data/svg-image.html")
    params = f"scale_factor={scale}"
    response = __call_convert_html(
        base_url=test_parameters.base_url,
        request_session=test_parameters.request_session,
        data=html,
        print_error=True,
        parameters=params,
    )
    assert response.status_code == 200

    # Render first page to PNG at high rasterization scale to reveal anti-aliasing differences
    doc = pymupdf.open(stream=response.content, filetype="pdf")
    page = doc.load_page(0)
    # 10x zoom to better visualize quality differences coming from device scale factor
    zoom = 10.0
    mat = pymupdf.Matrix(zoom, zoom)
    page_png_bytes = page.get_pixmap(matrix=mat).tobytes("png")
    flush_tmp_file(f"test_convert_svg_image_scale_{scale}.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    flush_tmp_file(f"test_convert_svg_image_scale_{scale}-x{int(zoom)}.png", page_png_bytes, test_parameters.flush_tmp_file_enabled)

    # Determine reference path
    # Use a stable string format for floating point values in filenames
    scale_str = ("%g" % scale).rstrip("0").rstrip(".") if "." in f"{scale}" else f"{scale}"
    # Ensure we keep at least one decimal for integer-like floats (e.g., 1.0 -> 1.0)
    if scale.is_integer():
        scale_str = f"{int(scale)}.0"
    ref_path = Path(f"tests/test-data/expected/svg-image-ref-scale-{scale_str}.png")

    # Open produced image
    produced_img = Image.open(io.BytesIO(page_png_bytes))

    if not ref_path.exists():
        import os
        if os.environ.get("UPDATE_EXPECTED_REFS", "0") == "1":
            # Generate the missing reference files: hi-res PNG (10x) and matching PDF next to it
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_bytes(page_png_bytes)
            pdf_ref_path = ref_path.with_suffix(".pdf")
            pdf_ref_path.write_bytes(response.content)
            pytest.skip(
                f"Reference {ref_path} (and {pdf_ref_path}) was missing and has been generated at 10x raster scale. Re-run tests."
            )
        else:
            pytest.skip(
                f"Missing reference image {ref_path}. Set UPDATE_EXPECTED_REFS=1 to generate references (PNG and PDF), "
                f"then commit them under tests/test-data/expected."
            )

    ref_image = Image.open(ref_path)
    # Basic sanity: mode and size should match
    assert produced_img.mode == ref_image.mode and produced_img.size == ref_image.size, (
        f"Image mode/size mismatch for scale={scale}. "
        f"Got mode={produced_img.mode}, size={produced_img.size}; "
        f"expected mode={ref_image.mode}, size={ref_image.size} from {ref_path}"
    )

    # Pixel-by-pixel comparison
    diff_bbox = ImageChops.difference(produced_img, ref_image).getbbox()
    assert diff_bbox is None, f"Rendered image differs from reference for scale={scale} at bbox={diff_bbox}"


def test_convert_incorrect_data(test_parameters: TestParameters) -> None:
    wrong_data = bytes([0xFF])
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=wrong_data, print_error=False)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "variant, is_supported",
    [
        ("pdf/a-1b", True),
        ("pdf/a-2b", True),
        ("pdf/a-3b", True),
        ("pdf/a-4b", True),
        ("pdf/a-2u", True),
        ("pdf/a-3u", True),
        ("pdf/a-4u", True),
        ("", True),
        ("pdf/a-5b", False),
        ("pdf/a-5u", False),
        ("some_string", False),
    ],
)
def test_supported_pdf_variants(variant: str, is_supported: bool, test_parameters: TestParameters) -> None:
    simple_html = f"<html><body>Pdf variant {variant}</body</html>"
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=simple_html, print_error=True, parameters=f"pdf_variant={variant}")
    if is_supported:
        assert response.status_code == 200
        stream = io.BytesIO(response.content)
        pdf_reader = PyPDF.PdfReader(stream)
        total_pages = len(pdf_reader.pages)
        assert total_pages == 1
        first_page = pdf_reader.pages[0].extract_text()
        assert f"Pdf variant {variant}" in first_page
        result_metadata_variant = __get_pdf_variant_from_metadata(pdf_reader)
        assert variant == result_metadata_variant
    else:
        assert response.status_code == 400


def test_convert_html_with_custom_metadata(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/html-with-custom-metadata.html")
    # Enable inclusion of custom metadata in the generated PDF
    response = __call_convert_html(
        base_url=test_parameters.base_url,
        request_session=test_parameters.request_session,
        data=html,
        print_error=True,
        parameters="custom_metadata=true",
    )

    assert response.status_code == 200
    flush_tmp_file("test_convert_html_with_custom_metadata.pdf", response.content, test_parameters.flush_tmp_file_enabled)

    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)

    # Basic PDF validation
    assert len(pdf_reader.pages) == 1
    page_text = pdf_reader.pages[0].extract_text()
    assert "Lorem ipsum dolor sit amet, consectetur adipiscing elit." in page_text

    # Validate metadata populated from HTML meta tags
    metadata = pdf_reader.metadata
    assert metadata is not None, "Expected metadata to be present when custom_metadata=true"

    title: str = metadata.get("/Title")
    author: str = metadata.get("/Author")
    keywords: str = metadata.get("/Keywords")
    creator: str = metadata.get("/Creator")
    producer: str = metadata.get("/Producer")

    assert title == "test with custom metadata"
    assert "Jane Doe, John Doe" in author
    assert "HTML, CSS, PDF, custom, fields, metadata" in keywords
    assert creator == "HTML generator"
    assert producer.startswith("WeasyPrint")


def __get_pdf_variant_from_metadata(pdf_reader: PyPDF.PdfReader) -> str:
    if pdf_reader.xmp_metadata and pdf_reader.xmp_metadata.rdf_root:
        for rdf_node in pdf_reader.xmp_metadata.rdf_root.childNodes:
            part = rdf_node.attributes.get("pdfaid:part")
            conformance = rdf_node.attributes.get("pdfaid:conformance")
            if part and conformance:
                return f"pdf/a-{part.value}{conformance.value}".lower()
    return ""


def __load_test_html(file_path: str) -> str:
    with Path(file_path).open(encoding="utf-8") as html_file:
        html = html_file.read()
        return html

def __call_convert_html_with_attachments(base_url: str, request_session: requests.Session, data, print_error, parameters=None, files: list[tuple[str, tuple[str, bytes, str | None]]] | None = None) -> requests.Response:
    url = f"{base_url}/convert/html-with-attachments"
    headers = {"Accept": "*/*"}
    payload = {"html": data}
    try:
        response = request_session.request(method="POST", url=url, headers=headers, data=payload, files=files,
                                           verify=True, params=parameters)
        if response.status_code // 100 != 2 and print_error:
            logging.error(f"Error: Unexpected response: '{response}'")
            logging.error(f"Error: Response content: '{response.content}'")
        return response
    except requests.exceptions.RequestException as e:
        logging.error(f"Error: {e}")
        raise


def __call_convert_html(base_url: str, request_session: requests.Session, data, print_error, parameters=None) -> requests.Response:
    url = f"{base_url}/convert/html"
    headers = {"Accept": "*/*", "Content-Type": "text/html"}
    try:
        response = request_session.request(method="POST", url=url, headers=headers, data=data, verify=True, params=parameters)
        if response.status_code // 100 != 2 and print_error:
            logging.error(f"Error: Unexpected response: '{response}'")
            logging.error(f"Error: Response content: '{response.content}'")
        return response
    except requests.exceptions.RequestException as e:
        logging.error(f"Error: {e}")
        raise


def flush_tmp_file(file_name: str, file_bytes: bytes, flush_tmp_file_enabled: bool) -> None:
    if flush_tmp_file_enabled:
        with Path(file_name).open("wb") as f:
            f.write(file_bytes)


def __extract_all_attachments(reader: PyPDF.PdfReader):
    DictObj = PyPDF.generic.DictionaryObject
    IndObj  = PyPDF.generic.IndirectObject
    ArrObj  = PyPDF.generic.ArrayObject

    def _as_obj(x):
        return x.get_object() if isinstance(x, IndObj) else x

    def _yield_filespec(fs_obj, name_hint: str, source: str) -> Iterator[tuple[str, str]]:
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
