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
        assert "chart.js" in result.text  # CDN reference
        assert "queueChart" in result.text
        assert "resourceChart" in result.text


def test_dashboard_contains_required_elements():
    """Test dashboard HTML contains all required UI elements."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/dashboard")
        html_content = result.text

        # Check for key sections
        assert "Queue Size" in html_content
        assert "Active Conversions" in html_content
        assert "Error Rate" in html_content
        assert "Total Conversions" in html_content
        assert "Avg Response Time" in html_content
        assert "Uptime" in html_content

        # Check for charts (only 2 charts remain after removal)
        assert "Queue & Active Conversions" in html_content
        assert "Resource Usage" in html_content

        # Check for system info section
        assert "System Information" in html_content
        assert "Service Version" in html_content
        assert "WeasyPrint Version" in html_content
        assert "Chromium Version" in html_content


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
