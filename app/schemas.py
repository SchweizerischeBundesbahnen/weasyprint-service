from pydantic import BaseModel, Field


class VersionSchema(BaseModel):
    """Schema for response /version"""

    python: str = Field(title="Python", description="Python version")
    weasyprint: str = Field(title="WeasyPrint", description="WeasyPrint version")
    weasyprintService: str = Field(title="WeasyPrint Service", description="Service version")
    timestamp: str = Field(title="Build Timestamp", description="Build timestamp")
    chromium: str = Field(title="Chromium", description="Chromium version")


class ChromiumMetricsSchema(BaseModel):
    """Schema for Chromium performance and health metrics"""

    # HTML to PDF conversion metrics
    total_conversions: int = Field(description="Total successful HTML to PDF conversions")
    failed_conversions: int = Field(description="Total failed HTML to PDF conversion attempts")
    avg_conversion_time_ms: float = Field(description="Average HTML to PDF conversion time in milliseconds")

    # SVG to PNG conversion metrics
    total_svg_conversions: int = Field(description="Total successful SVG to PNG conversions")
    failed_svg_conversions: int = Field(description="Total failed SVG to PNG conversion attempts")
    avg_svg_conversion_time_ms: float = Field(description="Average SVG to PNG conversion time in milliseconds")

    # Error and health metrics
    error_rate_percent: float = Field(description="Overall conversion error rate as percentage (includes both HTML->PDF and SVG->PNG)")
    total_chromium_restarts: int = Field(description="Total Chromium browser restarts since startup")
    last_health_check: str = Field(description="Formatted timestamp of last health check (HH:MM:SS DD.MM.YYYY)")
    last_health_status: bool = Field(description="Result of last health check (true=healthy)")
    consecutive_failures: int = Field(description="Current consecutive conversion failures")
    uptime_seconds: float = Field(description="Browser uptime in seconds")

    # Resource usage metrics
    current_cpu_percent: float = Field(description="Current CPU usage percentage")
    avg_cpu_percent: float = Field(description="Average CPU usage percentage")
    total_memory_mb: float = Field(description="Total system memory in MB")
    available_memory_mb: float = Field(description="Available system memory in MB")
    current_chromium_memory_mb: float = Field(description="Current Chromium physical memory usage in MB")
    avg_chromium_memory_mb: float = Field(description="Average Chromium physical memory usage in MB")

    # Queue metrics
    queue_size: int = Field(description="Current number of requests waiting in queue")
    max_queue_size: int = Field(description="Maximum queue size observed since startup")
    active_conversions: int = Field(description="Current number of active conversions in progress")
    avg_queue_time_ms: float = Field(description="Average time requests spend waiting in queue (milliseconds)")
    max_concurrent_conversions: int = Field(description="Maximum allowed concurrent conversions (configured limit)")


class HealthSchema(BaseModel):
    """Schema for detailed health status response"""

    status: str = Field(description="Overall health status: healthy or unhealthy")
    version: str = Field(description="WeasyPrint service version")
    weasyprint_version: str = Field(description="WeasyPrint library version")
    chromium_running: bool = Field(description="Whether Chromium browser is running")
    chromium_version: str | None = Field(description="Chromium version if available")
    health_monitoring_enabled: bool = Field(description="Whether background health monitoring is active")
    metrics: ChromiumMetricsSchema = Field(description="Performance and health metrics")
