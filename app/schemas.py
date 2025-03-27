from marshmallow import Schema, fields


class VersionSchema(Schema):
    """Schema for response /version"""

    python = fields.String(required=True, description="Python version")
    weasyprint = fields.String(required=True, description="WeasyPrint version")
    weasyprintService = fields.String(required=False, description="Service version")
    timestamp = fields.String(required=False, description="Build timestamp")
    chromium = fields.String(required=False, description="Chromium version")
