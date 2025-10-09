import os
import platform
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.weasyprint_controller import app


def test_version():
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["WEASYPRINT_SERVICE_BUILD_TIMESTAMP"] = "test2"
    with TestClient(app) as test_client:
        version = test_client.get("/version").json()

        assert version["python"] == platform.python_version()
        assert version["weasyprint"] is not None
        assert version["weasyprintService"] == "test1"
        assert version["timestamp"] == "test2"
        # Chromium version is fetched from ChromiumManager, can be None if browser not started or a version string
        assert version["chromium"] is None or isinstance(version["chromium"], str)


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


def test_health_with_chromium_unhealthy():
    """Test /health endpoint returns 503 when Chromium health check fails at runtime."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Mock ChromiumManager to simulate Chromium health check failing at runtime
    with patch("app.weasyprint_controller.get_chromium_manager") as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.health_check = AsyncMock(return_value=False)
        mock_get_manager.return_value = mock_manager

        with TestClient(app) as test_client:
            result = test_client.get("/health")

            assert result.status_code == 503
            assert result.text == "Service Unavailable"
