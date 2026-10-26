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
    """Test /metrics endpoint updates gauges from the conversion metrics."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with patch("app.metrics_server.update_gauges") as mock_update_gauges, TestClient(metrics_app) as test_client:
        result = test_client.get("/metrics")

        # Verify update_gauges was called
        assert mock_update_gauges.called

        # Verify successful response
        assert result.status_code == 200


def test_metrics_endpoint_contains_custom_conversion_metrics():
    """Test /metrics endpoint contains the custom conversion metrics, and none of the browser."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(metrics_app) as test_client:
        result = test_client.get("/metrics")
        content = result.text

        # Note: These will be 0 or default values since we're not running actual conversions
        assert "pdf_generations_total" in content
        assert "pdf_generation_failures_total" in content
        assert "pdf_generation_duration_seconds" in content
        assert "pdf_generation_error_rate_percent" in content
        assert "uptime_seconds" in content
        assert "system_memory_total_bytes" in content
        assert "system_memory_available_bytes" in content
        for removed in ("svg_conversion", "chromium", "cpu_percent", "queue_size", "active_pdf_generations"):
            assert removed not in content


def test_update_gauges_reads_the_conversion_metrics():
    """The gauges take the values of the conversion metrics."""
    from app import prometheus_metrics
    from app.conversion_metrics import ConversionMetrics

    metrics = ConversionMetrics()
    metrics.record_success(3000.0)
    metrics.record_failure()

    prometheus_metrics.update_gauges(metrics)

    assert prometheus_metrics.pdf_generation_error_rate_percent._value.get() == 50.0
    assert prometheus_metrics.avg_pdf_generation_time_seconds._value.get() == 3.0
    assert prometheus_metrics.system_memory_total_bytes._value.get() > 0


def test_update_gauges_survives_broken_metrics():
    """A failure while reading the metrics must not propagate to the caller."""
    from unittest.mock import MagicMock

    from app.prometheus_metrics import update_gauges

    broken = MagicMock()
    broken.get_metrics.side_effect = RuntimeError("no metrics")

    update_gauges(broken)

    broken.get_metrics.assert_called_once()
