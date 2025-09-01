from pydantic import BaseModel, Field


class VersionSchema(BaseModel):
    """Schema for response /version"""

    python: str = Field(title="Python", description="Python version")
    weasyprint: str = Field(title="WeasyPrint", description="WeasyPrint version")
    weasyprintService: str = Field(title="WeasyPrint Service", description="Service version")
    timestamp: str = Field(title="Build Timestamp", description="Build timestamp")
    chromium: str = Field(title="Chromium", description="Chromium version")
