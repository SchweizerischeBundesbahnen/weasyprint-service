import pytest

from app.schemas import VersionSchema


def test_version_schema_valid():
    data = {"python": "3.11.7", "weasyprint": "60.1", "weasyprintService": "1.0.0", "timestamp": "2025-03-25T14:00:00Z", "chromium": "121.0.0.0"}

    schema = VersionSchema()
    result = schema.load(data)

    assert result["python"] == data["python"]
    assert result["weasyprint"] == data["weasyprint"]
    assert result["weasyprintService"] == data["weasyprintService"]
    assert result["timestamp"] == data["timestamp"]
    assert result["chromium"] == data["chromium"]


def test_version_schema_missing_required():
    data = {"weasyprint": "60.1"}

    schema = VersionSchema()
    with pytest.raises(Exception) as excinfo:
        schema.load(data)

    assert "python" in str(excinfo.value)
