from pydantic import BaseModel, Field


class VersionSchema(BaseModel):
    """Schema for response /version"""

    python: str = Field(description="Python version")
    weasyprint: str = Field(description="WeasyPrint version")
    weasyprintService: str = Field(description="Service version")
    timestamp: str = Field(description="Build timestamp")
    chromium: str = Field(description="Chromium version")
