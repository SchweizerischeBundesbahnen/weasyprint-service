"""Tests for static files endpoint."""

import os

from fastapi.testclient import TestClient

from app.weasyprint_controller import app


def test_static_files_serve_openapi_json():
    """Test /static/openapi.json returns JSON file."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/openapi.json")

        assert result.status_code == 200
        assert "application/json" in result.headers["content-type"]
        # Check it's valid JSON with expected OpenAPI structure
        json_data = result.json()
        assert "openapi" in json_data
        assert "info" in json_data
        assert "paths" in json_data


def test_static_files_serve_chart_js():
    """Test /static/chart.umd.min.js returns JavaScript file."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/chart.umd.min.js")

        assert result.status_code == 200
        # FastAPI FileResponse uses application/javascript or text/javascript
        assert "javascript" in result.headers["content-type"] or result.headers["content-type"] == "application/octet-stream"
        assert len(result.content) > 0


def test_static_files_serve_readme():
    """Test /static/README.md returns markdown file."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/README.md")

        assert result.status_code == 200
        # Check content type is text/markdown or text/plain
        assert "text/" in result.headers["content-type"] or result.headers["content-type"] == "application/octet-stream"
        assert len(result.content) > 0


def test_static_files_serve_png_image():
    """Test /static/note.png returns PNG image."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/note.png")

        assert result.status_code == 200
        assert "image/png" in result.headers["content-type"]
        # PNG files start with magic bytes 89 50 4E 47
        assert result.content[:4] == b"\x89PNG"


def test_static_files_not_found():
    """Test /static/nonexistent returns 404."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/nonexistent.txt")

        assert result.status_code == 404
        assert result.content == b""  # Empty response body


def test_static_files_path_traversal_dotdot():
    """Test path traversal with .. is blocked."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/../weasyprint_controller.py")

        assert result.status_code == 404
        # FastAPI returns JSON error when path doesn't match route pattern
        # Our endpoint catches it when path matches but contains ".."


def test_static_files_path_traversal_dotdot_in_path():
    """Test path traversal with .. inside path is blocked."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        # FastAPI normalizes paths, but our is_relative_to() check catches traversal
        result = test_client.get("/static/subdir/../../../etc/passwd")

        # Should return 404 (either from FastAPI normalization or our validation)
        assert result.status_code == 404


def test_static_files_path_traversal_absolute():
    """Test absolute path is blocked."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static//etc/passwd")

        assert result.status_code == 404
        assert result.content == b""


def test_static_files_path_traversal_backslash():
    """Test path traversal with backslash is blocked (Windows)."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/\\..\\weasyprint_controller.py")

        assert result.status_code == 404
        assert result.content == b""


def test_static_files_nested_path():
    """Test that subdirectory access would return 404 (no subdirs in static/)."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/subdir/file.txt")

        assert result.status_code == 404
        assert result.content == b""


def test_static_files_empty_path():
    """Test empty path returns 404."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        result = test_client.get("/static/")

        assert result.status_code == 404
        assert result.content == b""


def test_static_files_directory_access():
    """Test accessing directory instead of file returns 404."""
    os.environ["WEASYPRINT_SERVICE_VERSION"] = "test1"

    with TestClient(app) as test_client:
        # Try to access the static directory itself
        result = test_client.get("/static/.")

        assert result.status_code == 404
        assert result.content == b""
