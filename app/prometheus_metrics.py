"""
Prometheus metrics collectors for weasyprint-service.

This module defines the custom Prometheus metrics of the HTML to PDF conversions.

Note: Counters are incremented when events occur (not synced from external state).
      Gauges are updated when the metrics are served.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from app.conversion_metrics import ConversionMetrics


logger = logging.getLogger(__name__)

_BYTES_PER_MB = 1024 * 1024

# Conversion counters - these are incremented when events occur
# DO NOT set these directly - use the increment functions below
pdf_generations_total = Counter(
    "pdf_generations_total",
    "Total number of successful HTML to PDF conversions",
)

pdf_generation_failures_total = Counter(
    "pdf_generation_failures_total",
    "Total number of failed HTML to PDF conversions",
)

# Conversion duration histogram - observations are added when conversions complete
pdf_generation_duration_seconds = Histogram(
    "pdf_generation_duration_seconds",
    "HTML to PDF conversion duration in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

pdf_generation_error_rate_percent = Gauge(
    "pdf_generation_error_rate_percent",
    "PDF generation error rate as percentage",
)

avg_pdf_generation_time_seconds = Gauge(
    "avg_pdf_generation_time_seconds",
    "Average HTML to PDF conversion time in seconds",
)

uptime_seconds = Gauge(
    "uptime_seconds",
    "Service uptime in seconds",
)

system_memory_total_bytes = Gauge(
    "system_memory_total_bytes",
    "Total system memory in bytes",
)

system_memory_available_bytes = Gauge(
    "system_memory_available_bytes",
    "Available system memory in bytes",
)


# Helper functions to increment counters (called when events occur)
def increment_pdf_generation_success(duration_seconds: float) -> None:
    """Increment successful PDF generation counter and record duration."""
    pdf_generations_total.inc()
    pdf_generation_duration_seconds.observe(duration_seconds)


def increment_pdf_generation_failure() -> None:
    """Increment failed PDF generation counter."""
    pdf_generation_failures_total.inc()


def update_gauges(conversion_metrics: ConversionMetrics) -> None:
    """
    Update the Prometheus gauges from the conversion metrics.

    Call it before serving metrics, so the gauges reflect the current state. It updates gauges
    only: counters are incremented when events occur, through the increment_* functions.

    Args:
        conversion_metrics: The metrics to read
    """
    try:
        metrics = conversion_metrics.get_metrics()
        pdf_generation_error_rate_percent.set(metrics["error_pdf_generation_rate_percent"])
        avg_pdf_generation_time_seconds.set(metrics["avg_pdf_generation_time_ms"] / 1000.0)
        uptime_seconds.set(metrics["uptime_seconds"])
        system_memory_total_bytes.set(metrics["total_memory_mb"] * _BYTES_PER_MB)
        system_memory_available_bytes.set(metrics["available_memory_mb"] * _BYTES_PER_MB)
        logger.debug("Prometheus gauges updated from the conversion metrics")
    except Exception as e:
        logger.exception("Failed to update Prometheus gauges: %s", e)
