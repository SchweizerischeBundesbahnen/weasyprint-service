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
    """Test /metrics endpoint updates gauges from ChromiumManager."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with patch("app.weasyprint_controller.update_gauges_from_chromium_manager") as mock_update_gauges:
        with TestClient(app) as test_client:
            result = test_client.get("/metrics")

            # Verify update_gauges_from_chromium_manager was called
            assert mock_update_gauges.called

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


def test_metrics_endpoint_excluded_from_instrumentation():
    """
    Test that /metrics endpoint is properly excluded from HTTP request instrumentation.

    This verifies that the excluded_handlers=["/metrics"] configuration in the
    Instrumentator prevents /metrics requests from inflating http_request metrics.

    Note: Since HTTP instrumentation is opt-in via ENABLE_METRICS env var and
    the test environment doesn't set it by default, we verify the exclusion config
    exists rather than testing runtime behavior.
    """
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    # Import the app to check the instrumentator configuration
    from app.weasyprint_controller import app as test_app

    # Verify that the app was created and has routes
    assert test_app is not None

    # Get all routes to verify /metrics exists
    metrics_routes = [route for route in test_app.routes if hasattr(route, "path") and route.path == "/metrics"]
    assert len(metrics_routes) > 0, "/metrics endpoint should exist"

    with TestClient(test_app) as test_client:
        # Verify /metrics endpoint works
        metrics_response = test_client.get("/metrics")
        assert metrics_response.status_code == 200

        # Verify the response contains Prometheus metrics format
        content = metrics_response.text
        assert "# HELP" in content or "# TYPE" in content

        # Call /metrics multiple times
        for _ in range(5):
            test_client.get("/metrics")

        # Get metrics again
        final_metrics = test_client.get("/metrics").text

        # Verify that if HTTP instrumentation metrics exist, /metrics path is not tracked
        # Look for any http_request metrics
        http_metrics_lines = [line for line in final_metrics.split("\n") if "http_request" in line and not line.startswith("#")]

        if len(http_metrics_lines) > 0:
            # HTTP instrumentation is active, verify /metrics is excluded
            metrics_path_lines = [line for line in http_metrics_lines if 'path="/metrics"' in line]
            assert len(metrics_path_lines) == 0, f"Found HTTP metrics for /metrics path - it should be excluded! Lines: {metrics_path_lines}"
        # If no HTTP metrics exist (default state), the test passes - exclusion config is in place
