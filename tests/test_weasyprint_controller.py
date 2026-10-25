import os
import platform
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import weasyprint_controller
from app.conversion_metrics import ConversionMetrics
from app.weasyprint_controller import app


def test_version():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["WEASYPRINT_SERVICE_BUILD_TIMESTAMP"] = "test2"
    with TestClient(app) as test_client:
        version = test_client.get("/version").json()

        assert version["apiVersion"] == 1
        assert version["python"] == platform.python_version()
        assert version["weasyprint"] is not None
        assert version["weasyprintService"] == "test1"
        assert version["timestamp"] == "test2"
        assert "chromium" not in version


def test_convert_html():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    with TestClient(app) as test_client:
        result = test_client.post(
            "/convert/html?base_url=/",
            content='<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>',
        )
        assert result.status_code == 200
        result = test_client.post(
            "/convert/html",
            content=b'\x81<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>',
        )
        assert result.status_code == 400


def test_convert_html_with_attachments():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    with TestClient(app) as test_client:
        result = test_client.post(
            "/convert/html-with-attachments?base_url=/",
            data={"html": '<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>'},
        )
        assert result.status_code == 200
        result = test_client.post(
            "/convert/html-with-attachments",
        )
        # Missing required form field 'html' should return 400 Bad Request
        assert result.status_code == 400


def test_convert_html_with_attachments_files():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    file1_path = Path("tests/test-data/html-with-attachments/attachment1.pdf")
    file2_path = Path("tests/test-data/html-with-attachments/attachment2.pdf")

    html = f'<html><body>Attachments: <a rel="attachment" href="{file2_path.name}">link</a></body></html>'

    files = [
        ("files", (file1_path.name, file1_path.read_bytes(), "application/pdf")),
        ("files", (file2_path.name, file2_path.read_bytes(), "application/pdf")),
    ]

    with TestClient(app) as test_client:
        result = test_client.post(
            "/convert/html-with-attachments?base_url=/",
            data={"html": html},
            files=files,
        )
        assert result.status_code == 200


def test_an_attachment_the_html_links_to_is_embedded():
    """The endpoint rewrites the href to a file: URI, which only its own temporary directory may serve.

    A status code alone would still pass with the attachment dropped, since
    WeasyPrint swallows a fetch which fails, so the result is read: this is what
    fails if the resource policy stops granting the endpoint its own directory.
    """
    attachment_path = Path("tests/test-data/html-with-attachments/attachment2.pdf")
    html = f'<html><head><link rel="attachment" href="{attachment_path.name}"></head><body>Attached</body></html>'
    files = [("files", (attachment_path.name, attachment_path.read_bytes(), "application/pdf"))]

    with TestClient(app) as test_client:
        result = test_client.post(
            "/convert/html-with-attachments?base_url=/",
            data={"html": html},
            files=files,
        )
        assert result.status_code == 200

    assert attachment_path.name in PdfReader(BytesIO(result.content)).attachments


def test_health_detailed_healthy():
    """Test /health?detailed=true returns JSON with the conversion metrics."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    metrics = ConversionMetrics()
    metrics.record_success(100.0)
    metrics.record_success(200.0)
    metrics.record_failure()

    with patch("app.conversion_metrics._conversion_metrics", metrics), TestClient(app) as test_client:
        result = test_client.get("/health?detailed=true")

    assert result.status_code == 200
    assert result.headers["content-type"] == "application/json"

    data = result.json()
    assert data["status"] == "healthy"
    assert data["version"] == "test1"
    assert data["weasyprint_version"] is not None
    assert data["svg_renderer"] == "weasysvg"
    assert set(data) == {"status", "version", "weasyprint_version", "svg_renderer", "metrics"}

    assert data["metrics"]["pdf_generations"] == 2
    assert data["metrics"]["failed_pdf_generations"] == 1
    assert data["metrics"]["avg_pdf_generation_time_ms"] == 150.0
    assert data["metrics"]["error_pdf_generation_rate_percent"] == 33.33
    assert data["metrics"]["uptime_seconds"] >= 0
    assert data["metrics"]["total_memory_mb"] > 0
    assert data["metrics"]["available_memory_mb"] > 0
    assert set(data["metrics"]) == {
        "pdf_generations",
        "failed_pdf_generations",
        "avg_pdf_generation_time_ms",
        "error_pdf_generation_rate_percent",
        "uptime_seconds",
        "total_memory_mb",
        "available_memory_mb",
    }


def test_health_detailed_false():
    """Test /health?detailed=false returns simple text response."""
    with TestClient(app) as test_client:
        result = test_client.get("/health?detailed=false")

    assert result.status_code == 200
    assert result.headers["content-type"] == "text/plain; charset=utf-8"
    assert result.text == "OK"


def test_health_default_no_parameter():
    """Test /health without detailed parameter returns simple text response (default behavior)."""
    with TestClient(app) as test_client:
        result = test_client.get("/health")

    assert result.status_code == 200
    assert result.headers["content-type"] == "text/plain; charset=utf-8"
    assert result.text == "OK"


def test_a_removed_query_parameter_is_ignored():
    """Old clients still send scale_factor, which no longer has an effect."""
    with TestClient(app) as test_client:
        result = test_client.post("/convert/html?scale_factor=2.0", content="<p>text</p>")

    assert result.status_code == 200


def test_pdf_rendering_runs_off_the_event_loop():
    """
    The PDF rendering must not run on the event loop.

    A held loop cannot act on SIGTERM, so the graceful shutdown timeout would only start
    once the rendering ended, and no other request would be served meanwhile.
    """
    import asyncio

    ran_on_the_loop = {}
    real_html = weasyprint_controller.weasyprint.HTML

    def recording_html(*args, **kwargs):
        html = real_html(*args, **kwargs)
        real_write_pdf = html.write_pdf

        def write_pdf(*write_args, **write_kwargs):
            # get_running_loop only succeeds on the thread the loop runs on.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                ran_on_the_loop["value"] = False
            else:
                ran_on_the_loop["value"] = True
            return real_write_pdf(*write_args, **write_kwargs)

        html.write_pdf = write_pdf
        return html

    with patch.object(weasyprint_controller.weasyprint, "HTML", side_effect=recording_html), TestClient(app) as test_client:
        result = test_client.post("/convert/html", content="<p>text</p>")

    assert result.status_code == 200
    assert ran_on_the_loop["value"] is False, "The rendering ran on the event loop thread"


def test_concurrent_pdf_conversions_default():
    """Without the variable the limit falls back to the default."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MAX_CONCURRENT_PDF_CONVERSIONS", None)
        assert weasyprint_controller.get_max_concurrent_pdf_conversions() == weasyprint_controller.DEFAULT_MAX_CONCURRENT_PDF_CONVERSIONS


def test_concurrent_pdf_conversions_reads_the_variable():
    """A valid value is used as is."""
    with patch.dict(os.environ, {"MAX_CONCURRENT_PDF_CONVERSIONS": "5"}):
        assert weasyprint_controller.get_max_concurrent_pdf_conversions() == 5


def test_concurrent_pdf_conversions_rejects_bad_values():
    """An invalid or out of range value falls back to the default."""
    for value in ("not-a-number", "0", "101"):
        with patch.dict(os.environ, {"MAX_CONCURRENT_PDF_CONVERSIONS": value}):
            assert weasyprint_controller.get_max_concurrent_pdf_conversions() == weasyprint_controller.DEFAULT_MAX_CONCURRENT_PDF_CONVERSIONS


def test_pdf_render_pool_follows_the_limit():
    """The startup sizes the rendering pool to the configured limit."""
    with patch.dict(os.environ, {"MAX_CONCURRENT_PDF_CONVERSIONS": "3"}), TestClient(app):
        assert app.state.pdf_render_executor._max_workers == 3
