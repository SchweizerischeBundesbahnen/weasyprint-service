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

    total_conversions: int = Field(description="Total successful SVG to PNG conversions")
    failed_conversions: int = Field(description="Total failed conversion attempts")
    error_rate_percent: float = Field(description="Error rate as percentage")
    total_restarts: int = Field(description="Total browser restarts since startup")
    avg_conversion_time_ms: float = Field(description="Average conversion time in milliseconds")
    last_health_check: float = Field(description="Timestamp of last health check (Unix time)")
    last_health_status: bool = Field(description="Result of last health check (true=healthy)")
    consecutive_failures: int = Field(description="Current consecutive conversion failures")
    uptime_seconds: float = Field(description="Browser uptime in seconds")


class HealthSchema(BaseModel):
    """Schema for detailed health status response"""

    status: str = Field(description="Overall health status: healthy or unhealthy")
    chromium_running: bool = Field(description="Whether Chromium browser is running")
    chromium_version: str | None = Field(description="Chromium version if available")
    health_monitoring_enabled: bool = Field(description="Whether background health monitoring is active")
    metrics: ChromiumMetricsSchema = Field(description="Performance and health metrics")
