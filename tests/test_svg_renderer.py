"""Tests for the SVG_RENDERER switch: chromium (default) or weasysvg."""

import importlib.metadata
import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from pypdf.generic import IndirectObject

from app import svg_renderer, weasyprint_controller
from app.chromium_manager import ChromiumManager
from app.weasyprint_controller import app

INLINE_SVG_HTML = '<html><body><p>Vector</p><svg width="120" height="80" viewBox="0 0 120 80"><rect x="10" y="10" width="100" height="60" fill="#c00"/><circle cx="60" cy="40" r="20" fill="#00c"/></svg></body></html>'


# --- Selection of the renderer ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("chromium", "chromium"),
        ("weasysvg", "weasysvg"),
        ("WeasySVG", "weasysvg"),
        ("  weasysvg \n", "weasysvg"),
        (" CHROMIUM ", "chromium"),
        ("", "chromium"),
        ("   ", "chromium"),
    ],
)
def test_get_svg_renderer_reads_the_variable(value, expected):
    with patch.dict(os.environ, {"SVG_RENDERER": value}):
        assert svg_renderer.get_svg_renderer() == expected


def test_get_svg_renderer_defaults_to_chromium():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SVG_RENDERER", None)
        assert svg_renderer.get_svg_renderer() == "chromium"


def test_get_svg_renderer_rejects_an_unknown_value(caplog):
    with patch.dict(os.environ, {"SVG_RENDERER": "resvg"}), caplog.at_level("WARNING", logger="app.svg_renderer"):
        assert svg_renderer.get_svg_renderer() == "chromium"
    assert "Invalid SVG_RENDERER value 'resvg', using default: chromium" in caplog.text


def test_configure_installs_weasysvg_once_in_weasysvg_mode():
    with patch.dict(os.environ, {"SVG_RENDERER": "weasysvg"}), patch.object(svg_renderer.weasysvg, "install") as install:
        assert svg_renderer.configure_svg_renderer() == "weasysvg"
    install.assert_called_once_with()


@pytest.mark.parametrize("value", ["chromium", "", "unknown"])
def test_configure_never_installs_weasysvg_in_chromium_mode(value):
    with patch.dict(os.environ, {"SVG_RENDERER": value}), patch.object(svg_renderer.weasysvg, "install") as install:
        assert svg_renderer.configure_svg_renderer() == "chromium"
    install.assert_not_called()


def test_weasysvg_version_is_the_installed_one():
    assert svg_renderer.get_weasysvg_version() == importlib.metadata.version("weasysvg")


# --- The service in each mode ---


@pytest.fixture
def weasysvg_mode():
    """Run the controller in weasysvg mode with a fresh, never started ChromiumManager."""
    manager = ChromiumManager()
    with (
        patch.object(weasyprint_controller, "SVG_RENDERER", "weasysvg"),
        patch("app.chromium_manager._chromium_manager", manager),
        patch.object(ChromiumManager, "start", AsyncMock(side_effect=AssertionError("Chromium must not start with weasysvg"))),
    ):
        yield manager


def test_weasysvg_mode_does_not_start_chromium(weasysvg_mode):
    with TestClient(app):
        assert weasysvg_mode.is_running() is False


def test_weasysvg_mode_health_is_ok_without_chromium(weasysvg_mode):
    with TestClient(app) as test_client:
        result = test_client.get("/health")

    assert result.status_code == 200
    assert result.text == "OK"


def test_weasysvg_mode_detailed_health_reports_no_chromium(weasysvg_mode):
    with TestClient(app) as test_client:
        result = test_client.get("/health?detailed=true")

    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "healthy"
    assert data["chromium_running"] is False
    assert data["chromium_version"] is None
    assert data["health_monitoring_enabled"] is False
    assert data["svg_renderer"] == "weasysvg"


def test_weasysvg_mode_version(weasysvg_mode):
    with TestClient(app) as test_client:
        version = test_client.get("/version").json()

    assert version["svgRenderer"] == "weasysvg"
    assert version["weasysvg"] == importlib.metadata.version("weasysvg")
    assert version["chromium"] is None


def test_weasysvg_mode_skips_the_svg_processor_and_counts_the_conversion(weasysvg_mode):
    with patch.object(weasyprint_controller, "SvgProcessor") as svg_processor, TestClient(app) as test_client:
        result = test_client.post("/convert/html", content=INLINE_SVG_HTML)
        failed = test_client.post("/convert/html", content=b"\x81<p>bad</p>")
        health = test_client.get("/health?detailed=true").json()

    assert result.status_code == 200
    assert failed.status_code == 400
    svg_processor.assert_not_called()
    assert health["metrics"]["pdf_generations"] == 1
    assert health["metrics"]["failed_pdf_generations"] == 1


def test_chromium_mode_version():
    with TestClient(app) as test_client:
        version = test_client.get("/version").json()

    assert version["svgRenderer"] == "chromium"
    assert version["weasysvg"] is None


def test_chromium_mode_detailed_health_names_the_renderer():
    with TestClient(app) as test_client:
        data = test_client.get("/health?detailed=true").json()

    assert data["svg_renderer"] == "chromium"


def test_chromium_mode_uses_the_svg_processor():
    with patch.object(weasyprint_controller, "SvgProcessor") as svg_processor, TestClient(app) as test_client:
        svg_processor.return_value.process_svg = AsyncMock(side_effect=lambda parsed: parsed)
        result = test_client.post("/convert/html", content=INLINE_SVG_HTML)

    assert result.status_code == 200
    svg_processor.assert_called_once()


# --- End to end, in a process of its own ---

# weasysvg patches WeasyPrint for the whole process and has no way back, so the end to end
# conversion runs in a child process. That process also takes the real import path: the
# variable is read and weasysvg is installed when the controller is imported.
CHILD_SCRIPT = """
import json, sys
from fastapi.testclient import TestClient
import weasysvg
from app import weasyprint_controller
from app.chromium_manager import get_chromium_manager

with TestClient(weasyprint_controller.app) as client:
    result = client.post("/convert/html", content=sys.argv[1])
    health = client.get("/health")
    running = get_chromium_manager().is_running()
with open(sys.argv[2], "wb") as target:
    target.write(result.content)
print(json.dumps({
    "status": result.status_code,
    "health": health.status_code,
    "renderer": weasyprint_controller.SVG_RENDERER,
    "installed": sorted(weasysvg.installed()),
    "chromium_running": running,
}))
"""


def _images_and_operators(resources, content: bytes, seen: set) -> tuple[int, bytes]:
    """Count image XObjects and collect the drawing operators of a page and its form XObjects."""
    images = 0
    operators = content
    xobjects = resources.get("/XObject", {}) if resources else {}
    for ref in xobjects.values():
        key = ref.idnum if isinstance(ref, IndirectObject) else id(ref)
        if key in seen:
            continue
        seen.add(key)
        xobject = ref.get_object()
        if xobject.get("/Subtype") == "/Image":
            images += 1
        elif xobject.get("/Subtype") == "/Form":
            nested_images, nested_operators = _images_and_operators(xobject.get("/Resources"), xobject.get_data(), seen)
            images += nested_images
            operators += b"\n" + nested_operators
    return images, operators


def test_weasysvg_mode_end_to_end_draws_vector_svg(tmp_path: Path):
    pdf_path = tmp_path / "weasysvg.pdf"
    env = {**os.environ, "SVG_RENDERER": "weasysvg", "METRICS_SERVER_ENABLED": "false"}
    completed = subprocess.run(
        [sys.executable, "-c", CHILD_SCRIPT, INLINE_SVG_HTML, str(pdf_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    outcome = json.loads(completed.stdout.strip().splitlines()[-1])

    assert outcome["status"] == 200
    assert outcome["health"] == 200
    assert outcome["renderer"] == "weasysvg"
    assert outcome["installed"], "weasysvg.install() was not called"
    assert outcome["chromium_running"] is False

    page = PdfReader(BytesIO(pdf_path.read_bytes())).pages[0]
    images, operators = _images_and_operators(page.get("/Resources"), page.get_contents().get_data(), set())
    assert images == 0, "The SVG became an image"
    # The rectangle and the circle are drawn as paths: a curve for the circle, a fill for both.
    assert b" c\n" in operators or b" c " in operators
    assert b"\nf\n" in operators or b"\nf*\n" in operators or b" f\n" in operators


def test_chromium_mode_end_to_end_draws_the_svg_as_an_image():
    """The counterpart: Chromium rasterizes the same SVG, so the page holds an image."""
    with TestClient(app) as test_client:
        result = test_client.post("/convert/html", content=INLINE_SVG_HTML)

    assert result.status_code == 200
    page = PdfReader(BytesIO(result.content)).pages[0]
    images, _ = _images_and_operators(page.get("/Resources"), page.get_contents().get_data(), set())
    assert images >= 1
