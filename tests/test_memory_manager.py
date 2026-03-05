import weakref
from unittest.mock import patch

import pytest

from app import memory_manager


@pytest.fixture(autouse=True)
def _reset():
    """Reset the cached enabled state before each test."""
    memory_manager._enabled = None


# ---------------------------------------------------------------------------
# Unit tests: is_enabled()
# ---------------------------------------------------------------------------


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RECLAIM_MEMORY_AFTER_CONVERSION", raising=False)
    assert memory_manager.is_enabled() is False


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "on"])
def test_enabled_with_truthy_values(monkeypatch, value):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", value)
    assert memory_manager.is_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "random", ""])
def test_disabled_with_falsy_values(monkeypatch, value):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", value)
    assert memory_manager.is_enabled() is False


def test_is_enabled_caches_result(monkeypatch):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    assert memory_manager.is_enabled() is True
    # Change env var — cached value should persist
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "false")
    assert memory_manager.is_enabled() is True


# ---------------------------------------------------------------------------
# Unit tests: reclaim_memory()
# ---------------------------------------------------------------------------


def test_reclaim_memory_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("RECLAIM_MEMORY_AFTER_CONVERSION", raising=False)
    with patch("gc.collect") as mock_gc:
        memory_manager.reclaim_memory()
        mock_gc.assert_not_called()


def test_reclaim_memory_calls_gc_when_enabled(monkeypatch):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    with patch("gc.collect") as mock_gc:
        memory_manager.reclaim_memory()
        mock_gc.assert_called_once()


def test_reclaim_memory_calls_malloc_trim_on_linux(monkeypatch):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setattr("platform.system", lambda: "Linux")

    mock_libc = type("MockLibc", (), {"malloc_trim": lambda self, x: None})()
    with patch("ctypes.CDLL", return_value=mock_libc) as mock_cdll:
        memory_manager.reclaim_memory()
        mock_cdll.assert_called_once_with("libc.so.6")


def test_reclaim_memory_skips_malloc_trim_on_non_linux(monkeypatch):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    with patch("ctypes.CDLL") as mock_cdll:
        memory_manager.reclaim_memory()
        mock_cdll.assert_not_called()


def test_reclaim_memory_handles_oserror_on_linux(monkeypatch):
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setattr("platform.system", lambda: "Linux")

    with patch("ctypes.CDLL", side_effect=OSError("libc not found")):
        with patch("gc.collect") as mock_gc:
            memory_manager.reclaim_memory()
            mock_gc.assert_called_once()


# ---------------------------------------------------------------------------
# Integration test: reclaim_memory called during PDF conversion
# ---------------------------------------------------------------------------


def test_reclaim_memory_called_after_html_conversion(monkeypatch):
    """Verify that reclaim_memory() is invoked after a successful /convert/html request."""
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setenv("WEASYPRINT_SERVICE_VERSION", "test1")

    from app.weasyprint_controller import app  # requires native libs (pango/gobject)
    from fastapi.testclient import TestClient

    with patch("app.memory_manager.reclaim_memory", wraps=memory_manager.reclaim_memory) as mock_reclaim:
        with TestClient(app) as test_client:
            result = test_client.post("/convert/html?base_url=/", content="<html><body>hello</body></html>")
            assert result.status_code == 200
            mock_reclaim.assert_called_once()


def test_reclaim_memory_called_after_html_with_attachments_conversion(monkeypatch):
    """Verify that reclaim_memory() is invoked after a successful /convert/html-with-attachments request."""
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setenv("WEASYPRINT_SERVICE_VERSION", "test1")

    from app.weasyprint_controller import app  # requires native libs (pango/gobject)
    from fastapi.testclient import TestClient

    with patch("app.memory_manager.reclaim_memory", wraps=memory_manager.reclaim_memory) as mock_reclaim:
        with TestClient(app) as test_client:
            result = test_client.post("/convert/html-with-attachments?base_url=/", data={"html": "<html><body>hello</body></html>"})
            assert result.status_code == 200
            mock_reclaim.assert_called_once()


def test_gc_collect_actually_reclaims_cyclic_references(monkeypatch):
    """Verify that reclaim_memory() breaks reference cycles via gc.collect."""
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")

    # Create a reference cycle that only gc.collect can break
    class CycleNode:
        def __init__(self):
            self.ref = None

    a = CycleNode()
    b = CycleNode()
    a.ref = b
    b.ref = a

    ref = weakref.ref(a)

    # Remove strong references — objects are now only reachable via the cycle
    del a, b

    memory_manager.reclaim_memory()

    # After reclaim_memory (which calls gc.collect), the cycle should be broken
    assert ref() is None
