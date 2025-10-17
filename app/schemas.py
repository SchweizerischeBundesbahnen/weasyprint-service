from pydantic import BaseModel, Field


class VersionSchema(BaseModel):
    """Schema for response /version"""

    python: str = Field(title="Python", description="Python version")
    weasyprint: str = Field(title="WeasyPrint", description="WeasyPrint version")
    weasyprintService: str | None = Field(title="WeasyPrint Service", description="Service version")
    timestamp: str | None = Field(title="Build Timestamp", description="Build timestamp")
    chromium: str | None = Field(title="Chromium", description="Chromium version")


class ChromiumMetricsSchema(BaseModel):
    """Schema for Chromium performance and health metrics"""

    # HTML to PDF generation metrics
    pdf_generations: int = Field(title="PDF Generations", description="Total successful HTML to PDF generations")
    failed_pdf_generations: int = Field(title="Failed PDF Generations", description="Total failed HTML to PDF generation attempts")
    avg_pdf_generation_time_ms: float = Field(title="Avg PDF Generation Time (ms)", description="Average HTML to PDF generation time in milliseconds (includes time for any SVG processing within the HTML)")

    # SVG to PNG conversion metrics (nested within PDF generations)
    total_svg_conversions: int = Field(title="Total SVG Conversions", description="Total successful SVG to PNG conversions (these occur within HTML to PDF generations)")
    failed_svg_conversions: int = Field(title="Failed SVG Conversions", description="Total failed SVG to PNG conversion attempts (these occur within HTML to PDF generations)")
    avg_svg_conversion_time_ms: float = Field(title="Avg SVG Conversion Time (ms)", description="Average SVG to PNG conversion time in milliseconds (for individual SVG elements within HTML)")

    # Error rate metrics
    error_pdf_generation_rate_percent: float = Field(title="PDF Generation Error Rate (%)", description="HTML to PDF generation error rate as percentage (based only on PDF generation attempts, not nested SVG conversions)")
    error_svg_conversion_rate_percent: float = Field(title="SVG Conversion Error Rate (%)", description="SVG to PNG conversion error rate as percentage (for SVG elements within HTML)")

    # Health metrics
    total_chromium_restarts: int = Field(title="Total Chromium Restarts", description="Total Chromium browser restarts since startup")
    last_health_check: str = Field(title="Last Health Check", description="Formatted timestamp of last health check (HH:MM:SS DD.MM.YYYY)")
    last_health_status: bool = Field(title="Last Health Status", description="Result of last health check (true=healthy)")
    uptime_seconds: float = Field(title="Uptime (seconds)", description="Browser uptime in seconds")

    # Resource usage metrics
    current_cpu_percent: float = Field(title="Current CPU (%)", description="Current CPU usage percentage")
    avg_cpu_percent: float = Field(title="Avg CPU (%)", description="Average CPU usage percentage")
    total_memory_mb: float = Field(title="Total Memory (MB)", description="Total system memory in MB")
    available_memory_mb: float = Field(title="Available Memory (MB)", description="Available system memory in MB")
    current_chromium_memory_mb: float = Field(title="Current Chromium Memory (MB)", description="Current Chromium physical memory usage in MB")
    avg_chromium_memory_mb: float = Field(title="Avg Chromium Memory (MB)", description="Average Chromium physical memory usage in MB")

    # Queue metrics
    queue_size: int = Field(title="Queue Size", description="Current number of requests waiting in queue")
    active_pdf_generations: int = Field(title="Active PDF Generations", description="Current number of active PDF generations in progress")
    avg_queue_time_ms: float = Field(title="Avg Queue Time (ms)", description="Average time requests spend waiting in queue (milliseconds)")
    max_concurrent_pdf_generations: int = Field(title="Max Concurrent PDF Generations", description="Maximum allowed concurrent PDF generations (configured limit)")


class HealthSchema(BaseModel):
    """Schema for detailed health status response"""

    status: str = Field(title="Status", description="Overall health status: healthy or unhealthy")
    version: str = Field(title="Version", description="WeasyPrint service version")
    weasyprint_version: str = Field(title="WeasyPrint Version", description="WeasyPrint library version")
    chromium_running: bool = Field(title="Chromium Running", description="Whether Chromium browser is running")
    chromium_version: str | None = Field(title="Chromium Version", description="Chromium version if available")
    health_monitoring_enabled: bool = Field(title="Health Monitoring Enabled", description="Whether background health monitoring is active")
    metrics: ChromiumMetricsSchema = Field(title="Metrics", description="Performance and health metrics")
