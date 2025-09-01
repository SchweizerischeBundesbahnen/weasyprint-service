import io
import logging
import time
from pathlib import Path
from typing import NamedTuple

import docker
import pymupdf
import pypdf as PyPDF
import pytest
import requests
from docker.models.containers import Container
from PIL import Image, ImageChops


class TestParameters(NamedTuple):
    __test__ = False
    base_url: str
    flush_tmp_file_enabled: bool
    request_session: requests.Session
    container: Container


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

    file1_path = Path("tests/test-data/test-svg-ref-image.png")
    file2_path = Path("tests/test-data/svg-image.html")

    file1_bytes = file1_path.read_bytes()
    file2_bytes = file2_path.read_bytes()

    files = [
        ("files", (file1_path.name, file1_bytes, "image/png")),
        ("files", (file2_path.name, file2_bytes, "text/html")),
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
    attachment_names: set[str] = set()
    # Prefer high-level API if available in pypdf 6
    names = getattr(pdf_reader, "attachments", None)
    if isinstance(names, dict):
        attachment_names = set(names.keys())
    else:
        # Fallback to reading from the embedded files name tree
        try:
            root = pdf_reader.trailer["/Root"]
            if "/Names" in root and "/EmbeddedFiles" in root["/Names"]:
                ef_names = root["/Names"]["/EmbeddedFiles"]["/Names"]
                # ef_names is an array: [name1, dict1, name2, dict2, ...]
                for i in range(0, len(ef_names), 2):
                    name_obj = ef_names[i]
                    if hasattr(name_obj, "get_object"):
                        name_obj = name_obj.get_object()
                    if isinstance(name_obj, (str, bytes)):
                        name = name_obj.decode("utf-8") if isinstance(name_obj, bytes) else name_obj
                        attachment_names.add(name)
        except Exception:
            # If anything goes wrong, keep set empty to fail assertion below for visibility
            pass

    assert file1_path.name in attachment_names
    assert file2_path.name in attachment_names


def test_convert_svg(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/svg-image.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200
    page_png_bytes = pymupdf.open(stream=response.content, filetype="pdf").load_page(0).get_pixmap().tobytes("png")
    flush_tmp_file("test_convert_svg.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    flush_tmp_file("test_convert_svg.png", page_png_bytes, test_parameters.flush_tmp_file_enabled)
    page_png = Image.open(io.BytesIO(page_png_bytes))
    ref_image = Image.open("tests/test-data/test-svg-ref-image.png")
    assert page_png.mode == ref_image.mode or page_png.size == ref_image.size
    assert ImageChops.difference(page_png, ref_image).getbbox() is None


def test_convert_incorrect_data(test_parameters: TestParameters) -> None:
    wrong_data = bytes([0xFF])
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=wrong_data, print_error=False)
    assert response.status_code == 400


def test_svg_has_no_extra_labels(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/test-svg.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200
    flush_tmp_file("test_svg_has_no_extra_labels.pdf", response.content, test_parameters.flush_tmp_file_enabled)
    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)
    total_pages = len(pdf_reader.pages)
    assert total_pages == 1
    page = pdf_reader.pages[0].extract_text()
    assert "cannotdisplay" not in page


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
