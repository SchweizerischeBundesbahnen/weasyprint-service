"""Tests for Prometheus metrics endpoint on dedicated metrics server."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.metrics_server import metrics_app
from app.weasyprint_controller import app


def test_metrics_endpoint_exists_on_metrics_server():
    """Test /metrics endpoint exists on metrics server and returns Prometheus text format."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(metrics_app) as test_client:
        result = test_client.get("/metrics")

        # Verify status code
        assert result.status_code == 200

        # Verify content type is Prometheus text format
        assert "text/plain" in result.headers["content-type"]

        # Verify response contains Prometheus metrics (at minimum the HTTP metrics from instrumentator)
        content = result.text
        assert "# HELP" in content or "# TYPE" in content


def test_metrics_endpoint_not_on_main_app():
    """Test /metrics endpoint returns 404 on main application."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/metrics")

        # Verify /metrics is NOT available on main app
        assert result.status_code == 404


def test_metrics_endpoint_updates_custom_metrics():
    """Test /metrics endpoint updates gauges from ChromiumManager."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with patch("app.metrics_server.update_gauges_from_chromium_manager") as mock_update_gauges, TestClient(metrics_app) as test_client:
        result = test_client.get("/metrics")

        # Verify update_gauges_from_chromium_manager was called
        assert mock_update_gauges.called

        # Verify successful response
        assert result.status_code == 200


def test_metrics_endpoint_contains_custom_chromium_metrics():
    """Test /metrics endpoint contains custom ChromiumManager metrics."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(metrics_app) as test_client:
        result = test_client.get("/metrics")
        content = result.text

        # Check for custom ChromiumManager metrics
        # Note: These will be 0 or default values since we're not running actual conversions
        assert "pdf_generations_total" in content
        assert "pdf_generation_failures_total" in content
        assert "svg_conversions_total" in content
        assert "svg_conversion_failures_total" in content
        assert "uptime_seconds" in content
        assert "chromium_memory_bytes" in content
        assert "system_memory_total_bytes" in content
