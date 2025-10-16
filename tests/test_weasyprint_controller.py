import os
import platform
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_health_detailed_healthy():
    """Test /health?detailed=true returns JSON with metrics when healthy."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Create mock manager
    mock_manager = AsyncMock()
    # Mock lifespan methods (start/stop are async)
    mock_manager.start = AsyncMock()
    mock_manager.stop = AsyncMock()
    # health_check() and other sync methods use MagicMock
    mock_manager.health_check = MagicMock(return_value=True)
    mock_manager.is_running = MagicMock(return_value=True)
    mock_manager.get_version = MagicMock(return_value="131.0.6778.33")
    mock_manager.health_check_enabled = True
    mock_manager.get_metrics = MagicMock(
        return_value={
            "total_conversions": 42,
            "failed_conversions": 3,
            "total_svg_conversions": 100,
            "failed_svg_conversions": 5,
            "error_rate_percent": 7.14,
            "total_chromium_restarts": 1,
            "avg_conversion_time_ms": 123.45,
            "avg_svg_conversion_time_ms": 50.12,
            "last_health_check": "12:34:56 01.02.2024",
            "last_health_status": True,
            "consecutive_failures": 0,
            "uptime_seconds": 3600.0,
            "current_cpu_percent": 5.5,
            "avg_cpu_percent": 3.2,
            "total_memory_mb": 16384.0,
            "available_memory_mb": 8192.0,
            "current_chromium_memory_mb": 128.5,
            "avg_chromium_memory_mb": 120.3,
            "queue_size": 2,
            "max_queue_size": 8,
            "active_conversions": 5,
            "avg_queue_time_ms": 15.75,
            "max_concurrent_conversions": 10,
        }
    )

    # Patch the singleton instance directly
    with patch("app.chromium_manager._chromium_manager", mock_manager):
        with TestClient(app) as test_client:
            result = test_client.get("/health?detailed=true")

            assert result.status_code == 200
            assert result.headers["content-type"] == "application/json"

            data = result.json()
            assert data["status"] == "healthy"
            assert data["version"] == "test1"
            assert data["weasyprint_version"] is not None
            assert data["chromium_running"] is True
            assert data["chromium_version"] == "131.0.6778.33"
            assert data["health_monitoring_enabled"] is True

            metrics = data["metrics"]
            assert metrics["total_conversions"] == 42
            assert metrics["failed_conversions"] == 3
            assert metrics["total_svg_conversions"] == 100
            assert metrics["failed_svg_conversions"] == 5
            assert metrics["error_rate_percent"] == 7.14
            assert metrics["total_chromium_restarts"] == 1
            assert metrics["avg_conversion_time_ms"] == 123.45
            assert metrics["avg_svg_conversion_time_ms"] == 50.12
            assert metrics["last_health_check"] == "12:34:56 01.02.2024"
            assert metrics["last_health_status"] is True
            assert metrics["consecutive_failures"] == 0
            assert metrics["uptime_seconds"] == 3600.0
            assert metrics["current_cpu_percent"] == 5.5
            assert metrics["avg_cpu_percent"] == 3.2
            assert metrics["total_memory_mb"] == 16384.0
            assert metrics["available_memory_mb"] == 8192.0
            assert metrics["current_chromium_memory_mb"] == 128.5
            assert metrics["avg_chromium_memory_mb"] == 120.3
            assert metrics["queue_size"] == 2
            assert metrics["max_queue_size"] == 8
            assert metrics["active_conversions"] == 5
            assert metrics["avg_queue_time_ms"] == 15.75
            assert metrics["max_concurrent_conversions"] == 10


def test_health_detailed_unhealthy():
    """Test /health?detailed=true returns 503 with JSON when unhealthy."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Create mock manager
    mock_manager = AsyncMock()
    # Mock lifespan methods (start/stop are async)
    mock_manager.start = AsyncMock()
    mock_manager.stop = AsyncMock()
    # health_check() and other sync methods use MagicMock
    mock_manager.health_check = MagicMock(return_value=False)
    mock_manager.is_running = MagicMock(return_value=False)
    mock_manager.get_version = MagicMock(return_value=None)
    mock_manager.health_check_enabled = True
    mock_manager.get_metrics = MagicMock(
        return_value={
            "total_conversions": 10,
            "failed_conversions": 5,
            "total_svg_conversions": 20,
            "failed_svg_conversions": 10,
            "error_rate_percent": 50.0,
            "total_chromium_restarts": 3,
            "avg_conversion_time_ms": 0.0,
            "avg_svg_conversion_time_ms": 0.0,
            "last_health_check": "",
            "last_health_status": False,
            "consecutive_failures": 3,
            "uptime_seconds": 0.0,
            "current_cpu_percent": 0.0,
            "avg_cpu_percent": 0.0,
            "total_memory_mb": 16384.0,
            "available_memory_mb": 2048.0,
            "current_chromium_memory_mb": 0.0,
            "avg_chromium_memory_mb": 0.0,
            "queue_size": 0,
            "max_queue_size": 0,
            "active_conversions": 0,
            "avg_queue_time_ms": 0.0,
            "max_concurrent_conversions": 10,
        }
    )

    # Patch the singleton instance directly
    with patch("app.chromium_manager._chromium_manager", mock_manager):
        with TestClient(app) as test_client:
            result = test_client.get("/health?detailed=true")

            assert result.status_code == 503
            assert result.headers["content-type"] == "application/json"

            data = result.json()
            assert data["status"] == "unhealthy"
            assert data["version"] == "test1"
            assert data["weasyprint_version"] is not None
            assert data["chromium_running"] is False
            assert data["chromium_version"] is None
            assert data["health_monitoring_enabled"] is True

            metrics = data["metrics"]
            assert metrics["total_conversions"] == 10
            assert metrics["failed_conversions"] == 5
            assert metrics["total_svg_conversions"] == 20
            assert metrics["failed_svg_conversions"] == 10
            assert metrics["error_rate_percent"] == 50.0
            assert metrics["total_chromium_restarts"] == 3
            assert metrics["consecutive_failures"] == 3
            assert metrics["last_health_status"] is False
            assert metrics["last_health_check"] == ""


def test_health_detailed_false():
    """Test /health?detailed=false returns simple text response."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Create mock manager
    mock_manager = AsyncMock()
    # Mock lifespan methods (start/stop are async)
    mock_manager.start = AsyncMock()
    mock_manager.stop = AsyncMock()
    # health_check() is a regular method, not async
    mock_manager.health_check = MagicMock(return_value=True)

    # Patch the singleton instance directly
    with patch("app.chromium_manager._chromium_manager", mock_manager):
        with TestClient(app) as test_client:
            result = test_client.get("/health?detailed=false")

            assert result.status_code == 200
            assert result.headers["content-type"] == "text/plain; charset=utf-8"
            assert result.text == "OK"


def test_health_default_no_parameter():
    """Test /health without detailed parameter returns simple text response (default behavior)."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Create mock manager
    mock_manager = AsyncMock()
    # Mock lifespan methods (start/stop are async)
    mock_manager.start = AsyncMock()
    mock_manager.stop = AsyncMock()
    # health_check() is a regular method, not async
    mock_manager.health_check = MagicMock(return_value=True)

    # Patch the singleton instance directly
    with patch("app.chromium_manager._chromium_manager", mock_manager):
        with TestClient(app) as test_client:
            result = test_client.get("/health")

            assert result.status_code == 200
            assert result.headers["content-type"] == "text/plain; charset=utf-8"
            assert result.text == "OK"


def test_health_detailed_with_health_monitoring_disabled():
    """Test /health?detailed=true when health monitoring is disabled."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Create mock manager
    mock_manager = AsyncMock()
    # Mock lifespan methods (start/stop are async)
    mock_manager.start = AsyncMock()
    mock_manager.stop = AsyncMock()
    # health_check() and other sync methods use MagicMock
    mock_manager.health_check = MagicMock(return_value=True)
    mock_manager.is_running = MagicMock(return_value=True)
    mock_manager.get_version = MagicMock(return_value="131.0.6778.33")
    mock_manager.health_check_enabled = False
    mock_manager.get_metrics = MagicMock(
        return_value={
            "total_conversions": 5,
            "failed_conversions": 0,
            "total_svg_conversions": 15,
            "failed_svg_conversions": 0,
            "error_rate_percent": 0.0,
            "total_chromium_restarts": 0,
            "avg_conversion_time_ms": 100.0,
            "avg_svg_conversion_time_ms": 45.0,
            "last_health_check": "",
            "last_health_status": False,
            "consecutive_failures": 0,
            "uptime_seconds": 1800.0,
            "current_cpu_percent": 2.5,
            "avg_cpu_percent": 1.8,
            "total_memory_mb": 16384.0,
            "available_memory_mb": 10240.0,
            "current_chromium_memory_mb": 95.5,
            "avg_chromium_memory_mb": 90.2,
            "queue_size": 0,
            "max_queue_size": 3,
            "active_conversions": 0,
            "avg_queue_time_ms": 5.25,
            "max_concurrent_conversions": 10,
        }
    )

    # Patch the singleton instance directly
    with patch("app.chromium_manager._chromium_manager", mock_manager):
        with TestClient(app) as test_client:
            result = test_client.get("/health?detailed=true")

            assert result.status_code == 200
            assert result.headers["content-type"] == "application/json"

            data = result.json()
            assert data["status"] == "healthy"
            assert data["version"] == "test1"
            assert data["weasyprint_version"] is not None
            assert data["health_monitoring_enabled"] is False
            assert data["metrics"]["last_health_check"] == ""
            assert data["metrics"]["total_conversions"] == 5
            assert data["metrics"]["total_svg_conversions"] == 15
