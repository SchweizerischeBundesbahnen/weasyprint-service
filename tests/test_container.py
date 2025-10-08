import io
import logging
import time
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import docker
import pypdf as PyPDF
import pytest
import requests
from docker.models.containers import Container
from PIL import Image, ImageChops

from tests import utils_pdf


class TestParameters(NamedTuple):
    base_url: str
    request_session: requests.Session
    container: Container
    # prevent pytest from collecting NamedTuple as a test
    __test__ = False


def wait_for_container_healthy(container: Container, max_wait_time: int = 60) -> None:
    """
    Wait for container to become healthy based on Docker healthcheck.

    Args:
        container: Docker container to wait for
        max_wait_time: Maximum time to wait in seconds (default: 60)

    Raises:
        TimeoutError: If container does not become healthy within max_wait_time
    """
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        container.reload()
        health_status = container.attrs.get("State", {}).get("Health", {}).get("Status")
        if health_status == "healthy":
            return
        time.sleep(1)

    # Timeout reached, print logs for debugging
    logs = container.logs().decode("utf-8")
    raise TimeoutError(f"Container did not become healthy within {max_wait_time} seconds. Logs:\n{logs}")


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
        auto_remove=True,  # Ensure container is automatically removed after it stops
        labels={"test-suite": "weasyprint-service"},
    )

    wait_for_container_healthy(container)

    yield container

    try:
        container.stop()
    except Exception:
        pass  # container may already be stopped/removed due to auto_remove=True


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
    request_session = requests.Session()
    yield TestParameters(base_url, request_session, weasyprint_container)
    request_session.close()


def test_container_no_error_logs(test_parameters: TestParameters) -> None:
    """Verify container logs contain expected startup messages and no errors."""
    logs = test_parameters.container.logs().decode("utf-8")
    log_lines = logs.splitlines()

    # Check line count is as expected
    assert len(log_lines) == 12, f"Expected 11 log lines, got {len(log_lines)}:\n{logs}"

    # Check for critical errors (should not contain ERROR or CRITICAL level messages)
    errors = [line for line in log_lines if " - ERROR - " in line or " - CRITICAL - " in line]
    assert not errors, f"Found error logs: {errors}"

    # Check for expected startup messages (ignore timestamps and specific details)
    expected_patterns = [
        "Logging initialized with level: INFO",
        "Log file: /opt/weasyprint/logs/weasyprint-service_",
        "Weasyprint service listening port: 9080",
        "Started server process",
        "Waiting for application startup",
        "Starting Chromium browser for SVG conversion",
        "Starting Chromium browser process via Playwright",
        "Chromium browser started successfully (PID: running)",
        "Chromium browser started successfully",
        "Application startup complete",
        "Uvicorn running on http://:9080",
        "\"GET /health HTTP/1.1\" 200 OK",
    ]

    log_text = "\n".join(log_lines)
    for pattern in expected_patterns:
        assert any(pattern in line for line in log_lines), f"Expected log pattern not found: '{pattern}'\nLogs:\n{log_text}"


def test_health(test_parameters: TestParameters) -> None:
    """Test /health endpoint returns service status and Chromium health."""
    url = f"{test_parameters.base_url}/health"
    response = test_parameters.request_session.get(url)

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "status" in data
    assert "chromium" in data

    # Verify Chromium is healthy
    assert data["chromium"] is True
    assert data["status"] == "healthy"


def test_convert_simple_html(test_parameters: TestParameters) -> None:
    simple_html = "<html><body>My test body</body</html>"

    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=simple_html, print_error=True)
    assert response.status_code == 200
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
    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)
    total_pages = len(pdf_reader.pages)
    assert total_pages == 4
    page = pdf_reader.pages[1].extract_text()
    assert "Test Specification" in page


def test_convert_html_with_svg_and_png_in_tables(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/html-with-svg-and-png-in-tables.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200

    # Render all pages to PNGs and compare all pages to references
    pages_png = utils_pdf.pdf_bytes_to_png_pages(response.content, zoom=5)

    ref_base = Path("tests/test-data/expected/html-with-svg-and-png-in-tables.png")
    try:
        utils_pdf.assert_png_pages_equal_to_refs(pages_png, ref_base, pdf_bytes=response.content)
    except utils_pdf.ReferenceGenerated:
        pytest.skip(f"Reference(s) {ref_base} were missing and have been generated (for all pages). Re-run tests.")
    except utils_pdf.ReferenceMissing as e:
        pytest.skip(str(e))


def test_convert_complex_html_without_embedded_attachments(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/test-specification.html")
    response = __call_convert_html_with_attachments(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200
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

    stream = io.BytesIO(response.content)
    pdf_reader = PyPDF.PdfReader(stream)

    # Basic PDF validation
    assert len(pdf_reader.pages) == 1
    page = pdf_reader.pages[0].extract_text()
    assert "Lorem ipsum dolor sit amet, consectetur adipiscing elit." in page

    # Validate attachments
    attachments = utils_pdf.extract_all_attachments(pdf_reader)

    expected = [
        (file1_path.name, "NamesTree"),
        (file2_path.name, "NamesTree"),
        (file3_path.name, "NamesTree"),
        (file1_path.name, "Annot:p0"),
        (file2_path.name, "Annot:p0"),
        (file1_path.name, "Annot:p0"),
    ]
    assert Counter(attachments) == Counter(expected)


def test_convert_svg(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/svg-image.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200

    # Render all pages to PNGs and compare all pages to references
    pages_png = utils_pdf.pdf_bytes_to_png_pages(response.content)

    ref_base = Path("tests/test-data/expected/svg-image-ref.png")
    try:
        utils_pdf.assert_png_pages_equal_to_refs(pages_png, ref_base, pdf_bytes=response.content)
    except utils_pdf.ReferenceGenerated:
        pytest.skip(f"Reference(s) {ref_base} were missing and have been generated (for all pages). Re-run tests.")
    except utils_pdf.ReferenceMissing as e:
        pytest.skip(str(e))


def test_convert_svg_as_base64(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/svg-image-as-base64.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200

    # Render all pages to PNGs and compare all pages to references
    pages_png = utils_pdf.pdf_bytes_to_png_pages(response.content)

    ref_base = Path("tests/test-data/expected/svg-image-as-base64-ref.png")
    try:
        utils_pdf.assert_png_pages_equal_to_refs(pages_png, ref_base, pdf_bytes=response.content)
    except utils_pdf.ReferenceGenerated:
        pytest.skip(f"Reference(s) {ref_base} were missing and have been generated (for all pages). Re-run tests.")
    except utils_pdf.ReferenceMissing as e:
        pytest.skip(str(e))


def test_convert_svg_without_xmlns(test_parameters: TestParameters) -> None:
    html = __load_test_html("tests/test-data/svg-image-without-xmlns.html")
    response = __call_convert_html(base_url=test_parameters.base_url, request_session=test_parameters.request_session, data=html, print_error=True)
    assert response.status_code == 200

    # Render all pages to PNGs and compare all pages to references
    pages_png = utils_pdf.pdf_bytes_to_png_pages(response.content)

    ref_base = Path("tests/test-data/expected/svg-image-ref.png")
    try:
        utils_pdf.assert_png_pages_equal_to_refs(pages_png, ref_base, pdf_bytes=response.content)
    except utils_pdf.ReferenceGenerated:
        pytest.skip(f"Reference(s) {ref_base} were missing and have been generated (for all pages). Re-run tests.")
    except utils_pdf.ReferenceMissing as e:
        pytest.skip(str(e))


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
    # 10x zoom to better visualize quality differences coming from device scale factor
    zoom = 10.0
    page_png_bytes = utils_pdf.pdf_bytes_to_png_pages(response.content, zoom=zoom)[0]

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
            pytest.skip(f"Reference {ref_path} (and {pdf_ref_path}) was missing and has been generated at 10x raster scale. Re-run tests.")
        else:
            pytest.skip(f"Missing reference image {ref_path}. Set UPDATE_EXPECTED_REFS=1 to generate references (PNG and PDF), then commit them under tests/test-data/expected.")

    ref_image = Image.open(ref_path)
    # Basic sanity: mode and size should match
    assert produced_img.mode == ref_image.mode and produced_img.size == ref_image.size, (
        f"Image mode/size mismatch for scale={scale}. Got mode={produced_img.mode}, size={produced_img.size}; expected mode={ref_image.mode}, size={ref_image.size} from {ref_path}"
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
        result_metadata_variant = utils_pdf.get_pdf_variant_from_metadata(pdf_reader)
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


def __load_test_html(file_path: str) -> str:
    with Path(file_path).open(encoding="utf-8") as html_file:
        html = html_file.read()
        return html


def __call_convert_html_with_attachments(base_url: str, request_session: requests.Session, data, print_error, parameters=None, files: list[tuple[str, tuple[str, bytes, str | None]]] | None = None) -> requests.Response:
    url = f"{base_url}/convert/html-with-attachments"
    headers = {"Accept": "*/*"}
    payload = {"html": data}
    try:
        response = request_session.request(method="POST", url=url, headers=headers, data=payload, files=files, verify=True, params=parameters)
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
