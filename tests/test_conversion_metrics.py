"""Tests for the metrics of the HTML to PDF conversions."""

from unittest.mock import patch

import pytest

from app import conversion_metrics
from app.conversion_metrics import ConversionMetrics, get_conversion_metrics


def test_new_metrics_are_zero():
    metrics = ConversionMetrics()

    assert metrics.total_conversions == 0
    assert metrics.failed_conversions == 0
    assert metrics.avg_conversion_time_ms == 0.0
    assert metrics.error_rate_percent == 0.0


def test_successes_give_the_average_duration():
    metrics = ConversionMetrics()
    metrics.record_success(100.0)
    metrics.record_success(300.0)

    assert metrics.total_conversions == 2
    assert metrics.avg_conversion_time_ms == 200.0
    assert metrics.error_rate_percent == 0.0


def test_failures_count_in_the_error_rate_but_not_in_the_average():
    metrics = ConversionMetrics()
    metrics.record_success(100.0)
    metrics.record_failure()
    metrics.record_failure()
    metrics.record_failure()

    assert metrics.failed_conversions == 3
    assert metrics.avg_conversion_time_ms == 100.0
    assert metrics.error_rate_percent == 75.0


def test_uptime_counts_from_the_start_time():
    metrics = ConversionMetrics(start_time=1000.0)
    with patch.object(conversion_metrics.time, "time", return_value=1042.5):
        assert metrics.uptime_seconds == 42.5


def test_get_metrics_rounds_and_adds_the_system_memory():
    metrics = ConversionMetrics()
    metrics.record_success(1.0)
    metrics.record_success(1.0)
    metrics.record_success(2.0)
    metrics.record_failure()
    memory = type("Memory", (), {"total": 4 * 1024 * 1024 * 1024, "available": 1536 * 1024 * 1024})()

    with patch.object(conversion_metrics.psutil, "virtual_memory", return_value=memory):
        result = metrics.get_metrics()

    assert result["pdf_generations"] == 3
    assert result["failed_pdf_generations"] == 1
    assert result["avg_pdf_generation_time_ms"] == 1.33
    assert result["error_pdf_generation_rate_percent"] == 25.0
    assert result["uptime_seconds"] >= 0
    assert result["total_memory_mb"] == 4096.0
    assert result["available_memory_mb"] == 1536.0


@pytest.fixture
def no_singleton():
    with patch.object(conversion_metrics, "_conversion_metrics", None):
        yield


@pytest.mark.usefixtures("no_singleton")
def test_get_conversion_metrics_returns_one_instance():
    first = get_conversion_metrics()

    assert isinstance(first, ConversionMetrics)
    assert get_conversion_metrics() is first
