"""Tests for weasyvsdx, which draws the Visio drawings of a document."""

import importlib.metadata
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import vsdx_renderer, weasyprint_controller
from app.weasyprint_controller import app

# --- Installation ---


@pytest.fixture
def installs():
    """Patch weasyvsdx, whose install would patch WeasyPrint for the whole process."""
    with (
        patch.object(vsdx_renderer.weasyvsdx, "find_converter", return_value="/usr/bin/vsd2xhtml") as find,
        patch.object(vsdx_renderer.weasyvsdx, "install") as weasyvsdx_install,
        patch.object(vsdx_renderer.weasyvsdx, "libvisio_version", return_value="0.1.7") as version,
        patch.dict(vsdx_renderer._LIBVISIO, clear=True),
    ):
        yield find, weasyvsdx_install, version


def test_configure_installs_weasyvsdx(installs):
    _, weasyvsdx_install, version = installs

    assert vsdx_renderer.configure_vsdx() is True
    assert vsdx_renderer.get_libvisio_version() == "0.1.7"
    weasyvsdx_install.assert_called_once_with(converter="/usr/bin/vsd2xhtml")
    version.assert_called_once_with("/usr/bin/vsd2xhtml")


def test_configure_patches_nothing_without_vsd2xhtml(installs, caplog):
    find, weasyvsdx_install, version = installs
    find.return_value = None

    with caplog.at_level("WARNING", logger="app.vsdx_renderer"):
        assert vsdx_renderer.configure_vsdx() is False
    assert vsdx_renderer.get_libvisio_version() is None
    weasyvsdx_install.assert_not_called()
    version.assert_not_called()
    assert "vsd2xhtml not found: install libvisio-tools" in caplog.text


def test_weasyvsdx_version_is_the_installed_one():
    assert vsdx_renderer.get_weasyvsdx_version() == importlib.metadata.version("weasyvsdx")


# --- /version ---


def test_version_names_weasyvsdx_and_libvisio():
    with patch.object(weasyprint_controller, "VSDX", True), patch.dict(vsdx_renderer._LIBVISIO, {"version": "0.1.7"}), TestClient(app) as test_client:
        version = test_client.get("/version").json()

    assert version["weasyvsdx"] == importlib.metadata.version("weasyvsdx")
    assert version["libvisio"] == "0.1.7"


def test_version_without_vsd2xhtml():
    with patch.object(weasyprint_controller, "VSDX", False), TestClient(app) as test_client:
        version = test_client.get("/version").json()

    assert version["weasyvsdx"] is None
    assert version["libvisio"] is None
