"""
Metrics of the HTML to PDF conversions.

The service keeps one ConversionMetrics for the whole process. The /health endpoint and the
Prometheus gauges read it; the /convert endpoints feed it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil

_BYTES_PER_MB = 1024 * 1024


@dataclass
class ConversionMetrics:
    """
    Counters and durations of the HTML to PDF conversions since the service started.

    Attributes:
        total_conversions: Successful conversions.
        failed_conversions: Failed conversions.
        total_conversion_time_ms: Time spent on successful conversions, for the average.
        start_time: When the metrics started to count, as time.time().
    """

    total_conversions: int = 0
    failed_conversions: int = 0
    total_conversion_time_ms: float = 0.0
    start_time: float = field(default_factory=time.time)

    def record_success(self, duration_ms: float) -> None:
        """Record a successful conversion and its duration."""
        self.total_conversions += 1
        self.total_conversion_time_ms += duration_ms

    def record_failure(self) -> None:
        """Record a failed conversion."""
        self.failed_conversions += 1

    @property
    def avg_conversion_time_ms(self) -> float:
        """Average duration of a successful conversion in milliseconds, 0 before the first one."""
        if self.total_conversions == 0:
            return 0.0
        return self.total_conversion_time_ms / self.total_conversions

    @property
    def error_rate_percent(self) -> float:
        """Failed conversions as a percentage of all attempts, 0 before the first one."""
        attempts = self.total_conversions + self.failed_conversions
        if attempts == 0:
            return 0.0
        return self.failed_conversions / attempts * 100.0

    @property
    def uptime_seconds(self) -> float:
        """Seconds since the metrics started to count."""
        return time.time() - self.start_time

    def get_metrics(self) -> dict[str, float | int]:
        """
        Return the metrics, rounded, with the memory of the system.

        Returns:
            The fields of ConversionMetricsSchema.
        """
        system_memory = psutil.virtual_memory()
        return {
            "pdf_generations": self.total_conversions,
            "failed_pdf_generations": self.failed_conversions,
            "avg_pdf_generation_time_ms": round(self.avg_conversion_time_ms, 2),
            "error_pdf_generation_rate_percent": round(self.error_rate_percent, 2),
            "uptime_seconds": round(self.uptime_seconds, 2),
            "total_memory_mb": round(system_memory.total / _BYTES_PER_MB, 2),
            "available_memory_mb": round(system_memory.available / _BYTES_PER_MB, 2),
        }


_conversion_metrics: ConversionMetrics | None = None


def get_conversion_metrics() -> ConversionMetrics:
    """
    Return the ConversionMetrics of the process, created on the first call.

    The endpoints take it as a FastAPI dependency.
    """
    global _conversion_metrics  # noqa: PLW0603
    if _conversion_metrics is None:
        _conversion_metrics = ConversionMetrics()
    return _conversion_metrics
