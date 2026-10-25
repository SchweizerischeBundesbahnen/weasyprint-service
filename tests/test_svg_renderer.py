"""Tests for the SVG renderer: weasysvg draws SVG, SVG_RENDERER only warns."""

import importlib.metadata
import logging
import os
from io import BytesIO
from unittest.mock import patch

import pytest
import weasysvg
from fastapi.testclient import TestClient
from pypdf import PdfReader
from pypdf.generic import IndirectObject

from app import svg_renderer, weasyprint_controller
from app.weasyprint_controller import app

INLINE_SVG_HTML = '<html><body><p>Vector</p><svg width="120" height="80" viewBox="0 0 120 80"><rect x="10" y="10" width="100" height="60" fill="#c00"/><circle cx="60" cy="40" r="20" fill="#00c"/></svg></body></html>'


# --- SVG_RENDERER ---


@pytest.mark.parametrize("value", ["chromium", " CHROMIUM ", "resvg"])
def test_another_renderer_logs_a_warning(value, caplog):
    with patch.dict(os.environ, {"SVG_RENDERER": value}), caplog.at_level(logging.WARNING, logger="app.svg_renderer"):
        svg_renderer.warn_about_svg_renderer()
    assert f"SVG_RENDERER={value.strip()} is no longer supported; weasysvg draws SVG" in caplog.text


@pytest.mark.parametrize("value", ["weasysvg", "WeasySVG", "  weasysvg \n", "", "   "])
def test_weasysvg_or_no_value_logs_nothing(value, caplog):
    with patch.dict(os.environ, {"SVG_RENDERER": value}), caplog.at_level(logging.WARNING, logger="app.svg_renderer"):
        svg_renderer.warn_about_svg_renderer()
    assert caplog.records == []


def test_unset_variable_logs_nothing(caplog):
    with patch.dict(os.environ, {}), caplog.at_level(logging.WARNING, logger="app.svg_renderer"):
        os.environ.pop("SVG_RENDERER", None)
        svg_renderer.warn_about_svg_renderer()
    assert caplog.records == []


@pytest.mark.parametrize("value", ["weasysvg", "", "chromium"])
def test_configure_always_installs_weasysvg(value):
    with patch.dict(os.environ, {"SVG_RENDERER": value}), patch.object(svg_renderer.weasysvg, "install") as install:
        assert svg_renderer.configure_svg_renderer() == "weasysvg"
    install.assert_called_once_with()


def test_weasysvg_version_is_the_installed_one():
    assert svg_renderer.get_weasysvg_version() == importlib.metadata.version("weasysvg")


# --- The service ---


def test_the_controller_installs_weasysvg_at_import():
    assert weasyprint_controller.SVG_RENDERER == "weasysvg"
    assert weasysvg.installed(), "weasysvg.install() was not called"


def test_health_is_ok():
    with TestClient(app) as test_client:
        result = test_client.get("/health")

    assert result.status_code == 200
    assert result.text == "OK"


def test_detailed_health_names_the_renderer_and_no_browser():
    with TestClient(app) as test_client:
        result = test_client.get("/health?detailed=true")

    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "healthy"
    assert data["svg_renderer"] == "weasysvg"
    for removed in ("chromium_running", "chromium_version", "health_monitoring_enabled"):
        assert removed not in data


def test_version_names_the_renderer_and_no_browser():
    with TestClient(app) as test_client:
        version = test_client.get("/version").json()

    assert version["svgRenderer"] == "weasysvg"
    assert version["weasysvg"] == importlib.metadata.version("weasysvg")
    assert "chromium" not in version


def test_conversions_are_counted():
    with TestClient(app) as test_client:
        before = test_client.get("/health?detailed=true").json()["metrics"]
        result = test_client.post("/convert/html", content=INLINE_SVG_HTML)
        failed = test_client.post("/convert/html", content=b"\x81<p>bad</p>")
        after = test_client.get("/health?detailed=true").json()["metrics"]

    assert result.status_code == 200
    assert failed.status_code == 400
    assert after["pdf_generations"] == before["pdf_generations"] + 1
    assert after["failed_pdf_generations"] == before["failed_pdf_generations"] + 1


# --- End to end ---


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


def test_svg_is_drawn_as_vector():
    with TestClient(app) as test_client:
        result = test_client.post("/convert/html", content=INLINE_SVG_HTML)

    assert result.status_code == 200
    page = PdfReader(BytesIO(result.content)).pages[0]
    images, operators = _images_and_operators(page.get("/Resources"), page.get_contents().get_data(), set())
    assert images == 0, "The SVG became an image"
    # The rectangle and the circle are drawn as paths: a curve for the circle, a fill for both.
    assert b" c\n" in operators or b" c " in operators
    assert b"\nf\n" in operators or b"\nf*\n" in operators or b" f\n" in operators
