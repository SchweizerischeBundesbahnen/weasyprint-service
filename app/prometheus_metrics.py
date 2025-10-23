"""
Prometheus metrics collectors for weasyprint-service.

This module defines custom Prometheus metrics that expose ChromiumManager
and application-level metrics for monitoring and observability.
"""

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram, Info

if TYPE_CHECKING:
    from app.chromium_manager import ChromiumManager


logger = logging.getLogger(__name__)


# Chromium conversion metrics
chromium_pdf_generations_total = Counter(
    "chromium_pdf_generations_total",
    "Total number of successful HTML to PDF conversions",
)

chromium_pdf_generation_failures_total = Counter(
    "chromium_pdf_generation_failures_total",
    "Total number of failed HTML to PDF conversions",
)

chromium_svg_conversions_total = Counter(
    "chromium_svg_conversions_total",
    "Total number of successful SVG to PNG conversions",
)

chromium_svg_conversion_failures_total = Counter(
    "chromium_svg_conversion_failures_total",
    "Total number of failed SVG to PNG conversions",
)

# Conversion duration histograms
chromium_pdf_generation_duration_seconds = Histogram(
    "chromium_pdf_generation_duration_seconds",
    "HTML to PDF conversion duration in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

chromium_svg_conversion_duration_seconds = Histogram(
    "chromium_svg_conversion_duration_seconds",
    "SVG to PNG conversion duration in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# Error rate gauges
chromium_pdf_generation_error_rate_percent = Gauge(
    "chromium_pdf_generation_error_rate_percent",
    "PDF generation error rate as percentage",
)

chromium_svg_conversion_error_rate_percent = Gauge(
    "chromium_svg_conversion_error_rate_percent",
    "SVG conversion error rate as percentage",
)

# Browser lifecycle metrics
chromium_restarts_total = Counter(
    "chromium_restarts_total",
    "Total number of Chromium browser restarts",
)

chromium_uptime_seconds = Gauge(
    "chromium_uptime_seconds",
    "Chromium browser uptime in seconds",
)

chromium_consecutive_failures = Gauge(
    "chromium_consecutive_failures",
    "Current number of consecutive health check failures",
)

# Resource usage metrics
chromium_cpu_percent = Gauge(
    "chromium_cpu_percent",
    "Current Chromium CPU usage percentage",
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
chromium_queue_size = Gauge(
    "chromium_queue_size",
    "Current number of requests in the conversion queue",
)

chromium_active_pdf_generations = Gauge(
    "chromium_active_pdf_generations",
    "Current number of active PDF generation processes",
)

chromium_queue_time_seconds = Histogram(
    "chromium_queue_time_seconds",
    "Time requests spend waiting in the queue",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# Browser info
chromium_info = Info(
    "chromium",
    "Chromium browser information",
)


def update_metrics_from_chromium_manager(chromium_manager: "ChromiumManager") -> None:
    """
    Update all Prometheus metrics from ChromiumManager metrics.

    This function should be called periodically or before serving metrics
    to ensure Prometheus gauges reflect the current state.

    Args:
        chromium_manager: ChromiumManager instance to collect metrics from
    """
    try:
        metrics = chromium_manager.get_metrics()

        # Update counters (set to current value - Prometheus counters should only increase)
        # Note: We update the internal _value directly since these are cumulative
        chromium_pdf_generations_total._value.set(float(metrics["pdf_generations"]))
        chromium_pdf_generation_failures_total._value.set(float(metrics["failed_pdf_generations"]))
        chromium_svg_conversions_total._value.set(float(metrics["total_svg_conversions"]))
        chromium_svg_conversion_failures_total._value.set(float(metrics["failed_svg_conversions"]))
        chromium_restarts_total._value.set(float(metrics["total_chromium_restarts"]))

        # Update gauges - convert to float to satisfy mypy type checking
        chromium_pdf_generation_error_rate_percent.set(float(metrics["error_pdf_generation_rate_percent"]))
        chromium_svg_conversion_error_rate_percent.set(float(metrics["error_svg_conversion_rate_percent"]))
        chromium_uptime_seconds.set(float(metrics["uptime_seconds"]))
        chromium_cpu_percent.set(float(metrics["current_cpu_percent"]))
        chromium_memory_bytes.set(float(metrics["current_chromium_memory_mb"]) * 1024 * 1024)  # Convert MB to bytes
        system_memory_total_bytes.set(float(metrics["total_memory_mb"]) * 1024 * 1024)  # Convert MB to bytes
        system_memory_available_bytes.set(float(metrics["available_memory_mb"]) * 1024 * 1024)  # Convert MB to bytes
        chromium_queue_size.set(float(metrics["queue_size"]))
        chromium_active_pdf_generations.set(float(metrics["active_pdf_generations"]))

        # Note: Histogram observations (duration and queue time) are recorded during actual conversions
        # in the ChromiumManager, not here. This function only updates counters and gauges.

        # Update browser info
        chromium_version = chromium_manager.get_version()
        if chromium_version:
            chromium_info.info({"version": chromium_version})

        logger.debug("Prometheus metrics updated from ChromiumManager")

    except Exception as e:
        logger.error("Failed to update Prometheus metrics: %s", e, exc_info=True)
