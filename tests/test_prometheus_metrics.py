"""Tests for Prometheus metrics endpoint."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.weasyprint_controller import app


def test_metrics_endpoint_exists():
    """Test /metrics endpoint exists and returns Prometheus text format."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/metrics")

        # Verify status code
        assert result.status_code == 200

        # Verify content type is Prometheus text format
        assert "text/plain" in result.headers["content-type"]

        # Verify response contains Prometheus metrics (at minimum the HTTP metrics from instrumentator)
        content = result.text
        assert "# HELP" in content or "# TYPE" in content


def test_metrics_endpoint_updates_custom_metrics():
    """Test /metrics endpoint updates custom metrics from ChromiumManager via middleware."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with patch("app.weasyprint_controller.update_metrics_from_chromium_manager") as mock_update_metrics:
        with TestClient(app) as test_client:
            result = test_client.get("/metrics")

            # Verify update_metrics_from_chromium_manager was called by middleware
            assert mock_update_metrics.called

            # Verify successful response
            assert result.status_code == 200


def test_metrics_endpoint_contains_custom_chromium_metrics():
    """Test /metrics endpoint contains custom ChromiumManager metrics."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/metrics")
        content = result.text

        # Check for custom ChromiumManager metrics
        # Note: These will be 0 or default values since we're not running actual conversions
        assert "chromium_pdf_generations_total" in content
        assert "chromium_pdf_generation_failures_total" in content
        assert "chromium_svg_conversions_total" in content
        assert "chromium_svg_conversion_failures_total" in content
        assert "chromium_uptime_seconds" in content
        assert "chromium_memory_bytes" in content
        assert "system_memory_total_bytes" in content
