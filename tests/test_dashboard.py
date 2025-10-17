"""Tests for monitoring dashboard endpoint."""

import os

from fastapi.testclient import TestClient

from app.weasyprint_controller import app


def test_dashboard_endpoint_returns_html():
    """Test /dashboard endpoint returns HTML page."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")

        assert result.status_code == 200
        assert result.headers["content-type"] == "text/html; charset=utf-8"
        assert "WeasyPrint Service Monitor" in result.text
        assert "chart.umd.min.js" in result.text  # Local Chart.js file
        assert "queueChart" in result.text
        assert "cpuChart" in result.text
        assert "memoryChart" in result.text


def test_dashboard_contains_required_elements():
    """Test dashboard HTML contains all required UI elements."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        html_content = result.text

        # Check for all 12 metric cards
        assert "Status" in html_content
        assert "Uptime" in html_content
        assert "Concurrent Slots" in html_content
        assert "Queue" in html_content
        assert "PDF Generations" in html_content
        assert "Avg Generation Time" in html_content
        assert "Failed Generations" in html_content
        assert "Generation Error Rate" in html_content
        assert "SVG Conversions" in html_content
        assert "Avg Conversion Time" in html_content
        assert "Failed Conversions" in html_content
        assert "Conversion Error Rate" in html_content

        # Check for charts (3 charts: Queue, CPU, Memory)
        assert "Queue & Active PDF Generations" in html_content
        assert "CPU Usage" in html_content
        assert "Memory Usage" in html_content

        # Check for version info in header
        assert "Service:" in html_content
        assert "WeasyPrint:" in html_content
        assert "Chromium:" in html_content
        assert "serviceVersion" in html_content
        assert "weasyprintVersion" in html_content
        assert "chromiumVersion" in html_content


def test_dashboard_auto_refresh_configured():
    """Test dashboard has auto-refresh configured."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        html_content = result.text

        # Check for auto-refresh implementation
        assert "setInterval" in html_content
        assert "updateMetrics" in html_content
        assert "5000" in html_content  # 5 second refresh interval


def test_dashboard_theme_light_by_default():
    """Test dashboard uses light theme by default when DASHBOARD_THEME is not set."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    # Remove DASHBOARD_THEME if it exists
    os.environ.pop("DASHBOARD_THEME", None)

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        assert result.status_code == 200
        assert 'data-theme="light"' in result.text


def test_dashboard_theme_light_explicit():
    """Test dashboard uses light theme when DASHBOARD_THEME=light."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["DASHBOARD_THEME"] = "light"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        assert result.status_code == 200
        assert 'data-theme="light"' in result.text


def test_dashboard_theme_dark():
    """Test dashboard uses dark theme when DASHBOARD_THEME=dark."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["DASHBOARD_THEME"] = "dark"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        assert result.status_code == 200
        assert 'data-theme="dark"' in result.text


def test_dashboard_theme_invalid_defaults_to_light():
    """Test invalid DASHBOARD_THEME value defaults to light theme."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["DASHBOARD_THEME"] = "invalid"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        assert result.status_code == 200
        assert 'data-theme="light"' in result.text


def test_dashboard_theme_case_insensitive():
    """Test DASHBOARD_THEME is case-insensitive."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"
    os.environ["DASHBOARD_THEME"] = "DARK"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        assert result.status_code == 200
        assert 'data-theme="dark"' in result.text
