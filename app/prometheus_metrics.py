"""
Prometheus metrics collectors for weasyprint-service.

This module defines custom Prometheus metrics that expose ChromiumManager
and application-level metrics for monitoring and observability.

Note: Counters are incremented when events occur (not synced from external state).
      Gauges are updated periodically to reflect current state.
"""

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram, Info

if TYPE_CHECKING:
    from app.chromium_manager import ChromiumManager


logger = logging.getLogger(__name__)


# Chromium conversion counters - these are incremented when events occur
# DO NOT set these directly - use the increment functions below
pdf_generations_total = Counter(
    "pdf_generations_total",
    "Total number of successful HTML to PDF conversions",
)

pdf_generation_failures_total = Counter(
    "pdf_generation_failures_total",
    "Total number of failed HTML to PDF conversions",
)

svg_conversions_total = Counter(
    "svg_conversions_total",
    "Total number of successful SVG to PNG conversions",
)

svg_conversion_failures_total = Counter(
    "svg_conversion_failures_total",
    "Total number of failed SVG to PNG conversions",
)

# Conversion duration histograms - observations are added when conversions complete
pdf_generation_duration_seconds = Histogram(
    "pdf_generation_duration_seconds",
    "HTML to PDF conversion duration in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

svg_conversion_duration_seconds = Histogram(
    "svg_conversion_duration_seconds",
    "SVG to PNG conversion duration in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# Error rate gauges
pdf_generation_error_rate_percent = Gauge(
    "pdf_generation_error_rate_percent",
    "PDF generation error rate as percentage",
)

svg_conversion_error_rate_percent = Gauge(
    "svg_conversion_error_rate_percent",
    "SVG conversion error rate as percentage",
)

avg_pdf_generation_time_seconds = Gauge(
    "avg_pdf_generation_time_seconds",
    "Average HTML to PDF conversion time in seconds",
)

avg_svg_conversion_time_seconds = Gauge(
    "avg_svg_conversion_time_seconds",
    "Average SVG to PNG conversion time in seconds",
)

# Browser lifecycle metrics
chromium_restarts_total = Counter(
    "chromium_restarts_total",
    "Total number of Chromium browser restarts",
)

uptime_seconds = Gauge(
    "uptime_seconds",
    "Service uptime in seconds",
)

chromium_consecutive_failures = Gauge(
    "chromium_consecutive_failures",
    "Current number of consecutive health check failures",
)

# Resource usage metrics
cpu_percent = Gauge(
    "cpu_percent",
    "Current CPU usage percentage",
)

chromium_memory_bytes = Gauge(
    "chromium_memory_bytes",
    "Current Chromium memory usage in bytes",
)

system_memory_total_bytes = Gauge(
    "system_memory_total_bytes",
    "Total system memory in bytes",
)

system_memory_available_bytes = Gauge(
    "system_memory_available_bytes",
    "Available system memory in bytes",
)

# Queue and concurrency metrics
queue_size = Gauge(
    "queue_size",
    "Current number of requests in the conversion queue",
)

active_pdf_generations = Gauge(
    "active_pdf_generations",
    "Current number of active PDF generation processes",
)

queue_time_seconds = Histogram(
    "queue_time_seconds",
    "Time requests spend waiting in the queue",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# Browser info
chromium_info = Info(
    "chromium",
    "Chromium browser information",
)


# Helper functions to increment counters (called when events occur)
def increment_pdf_generation_success(duration_seconds: float) -> None:
    """Increment successful PDF generation counter and record duration."""
    pdf_generations_total.inc()
    pdf_generation_duration_seconds.observe(duration_seconds)


def increment_pdf_generation_failure() -> None:
    """Increment failed PDF generation counter."""
    pdf_generation_failures_total.inc()


def increment_svg_conversion_success(duration_seconds: float) -> None:
    """Increment successful SVG conversion counter and record duration."""
    svg_conversions_total.inc()
    svg_conversion_duration_seconds.observe(duration_seconds)


def increment_svg_conversion_failure() -> None:
    """Increment failed SVG conversion counter."""
    svg_conversion_failures_total.inc()


def increment_chromium_restart() -> None:
    """Increment Chromium restart counter."""
    chromium_restarts_total.inc()


def update_gauges_from_chromium_manager(chromium_manager: "ChromiumManager") -> None:
    """
    Update Prometheus gauges from ChromiumManager current state.

    This function should be called before serving metrics to ensure
    gauges reflect the current state. It ONLY updates gauges, not counters.

    Note: Counters are incremented when events occur via the increment_* functions.

    Args:
        chromium_manager: ChromiumManager instance to collect metrics from
    """
    try:
        metrics = chromium_manager.get_metrics()

        # Update gauges only - convert to float to satisfy mypy type checking
        pdf_generation_error_rate_percent.set(float(metrics["error_pdf_generation_rate_percent"]))
        svg_conversion_error_rate_percent.set(float(metrics["error_svg_conversion_rate_percent"]))
        uptime_seconds.set(float(metrics["uptime_seconds"]))
        cpu_percent.set(float(metrics["current_cpu_percent"]))
        chromium_memory_bytes.set(float(metrics["current_chromium_memory_mb"]) * 1024 * 1024)  # Convert MB to bytes
        system_memory_total_bytes.set(float(metrics["total_memory_mb"]) * 1024 * 1024)  # Convert MB to bytes
        system_memory_available_bytes.set(float(metrics["available_memory_mb"]) * 1024 * 1024)  # Convert MB to bytes
        queue_size.set(float(metrics["queue_size"]))
        active_pdf_generations.set(float(metrics["active_pdf_generations"]))
        chromium_consecutive_failures.set(float(metrics.get("consecutive_failures", 0)))
        avg_pdf_generation_time_seconds.set(float(metrics["avg_pdf_generation_time_ms"]) / 1000.0)
        avg_svg_conversion_time_seconds.set(float(metrics["avg_svg_conversion_time_ms"]) / 1000.0)

        # Update browser info
        chromium_version = chromium_manager.get_version()
        if chromium_version:
            chromium_info.info({"version": chromium_version})

        logger.debug("Prometheus gauges updated from ChromiumManager")

    except Exception as e:
        logger.error("Failed to update Prometheus gauges: %s", e, exc_info=True)
