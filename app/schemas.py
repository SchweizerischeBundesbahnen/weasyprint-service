from pydantic import BaseModel, Field


class VersionSchema(BaseModel):
    """Schema for response /version"""

    # This is the JSON field name pdf-exporter reads.
    apiVersion: int = Field(title="API Version", description="API version for compatibility checking with pdf-exporter")  # noqa: N815
    python: str = Field(title="Python", description="Python version")
    weasyprint: str = Field(title="WeasyPrint", description="WeasyPrint version")
    # This is the JSON field name pdf-exporter reads.
    weasyprintService: str | None = Field(title="WeasyPrint Service", description="Service version")  # noqa: N815
    timestamp: str | None = Field(title="Build Timestamp", description="Build timestamp")
    svgRenderer: str | None = Field(default=None, title="SVG Renderer", description="Who draws SVG: always weasysvg (vector)")  # noqa: N815
    weasysvg: str | None = Field(default=None, title="weasysvg", description="weasysvg version")
    weasyvsdx: str | None = Field(default=None, title="weasyvsdx", description="weasyvsdx version, when it draws Visio drawings")
    libvisio: str | None = Field(default=None, title="libvisio", description="libvisio version weasyvsdx runs, when it finds vsd2xhtml")


class ConversionMetricsSchema(BaseModel):
    """Schema for the HTML to PDF conversion metrics"""

    pdf_generations: int = Field(title="PDF Generations", description="Total successful HTML to PDF generations")
    failed_pdf_generations: int = Field(title="Failed PDF Generations", description="Total failed HTML to PDF generation attempts")
    avg_pdf_generation_time_ms: float = Field(title="Avg PDF Generation Time (ms)", description="Average HTML to PDF generation time in milliseconds")
    error_pdf_generation_rate_percent: float = Field(title="PDF Generation Error Rate (%)", description="HTML to PDF generation error rate as percentage")
    uptime_seconds: float = Field(title="Uptime (seconds)", description="Service uptime in seconds")
    total_memory_mb: float = Field(title="Total Memory (MB)", description="Total system memory in MB")
    available_memory_mb: float = Field(title="Available Memory (MB)", description="Available system memory in MB")


class HealthSchema(BaseModel):
    """Schema for detailed health status response"""

    status: str = Field(title="Status", description="Overall health status: healthy or unhealthy")
    version: str = Field(title="Version", description="WeasyPrint service version")
    weasyprint_version: str = Field(title="WeasyPrint Version", description="WeasyPrint library version")
    svg_renderer: str | None = Field(default=None, title="SVG Renderer", description="Who draws SVG: always weasysvg (vector)")
    metrics: ConversionMetricsSchema = Field(title="Metrics", description="HTML to PDF conversion metrics")
