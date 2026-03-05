from unittest.mock import patch

from app import memory_manager


def _reset():
    """Reset the cached enabled state between tests."""
    memory_manager._enabled = None


def test_disabled_by_default(monkeypatch):
    _reset()
    monkeypatch.delenv("RECLAIM_MEMORY_AFTER_CONVERSION", raising=False)
    assert memory_manager.is_enabled() is False


def test_enabled_with_true(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    assert memory_manager.is_enabled() is True


def test_enabled_with_one(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "1")
    assert memory_manager.is_enabled() is True


def test_enabled_case_insensitive(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "True")
    assert memory_manager.is_enabled() is True


def test_disabled_with_false(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "false")
    assert memory_manager.is_enabled() is False


def test_reclaim_memory_noop_when_disabled(monkeypatch):
    _reset()
    monkeypatch.delenv("RECLAIM_MEMORY_AFTER_CONVERSION", raising=False)
    with patch("gc.collect") as mock_gc:
        memory_manager.reclaim_memory()
        mock_gc.assert_not_called()


def test_reclaim_memory_calls_gc_when_enabled(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    with patch("gc.collect") as mock_gc:
        memory_manager.reclaim_memory()
        mock_gc.assert_called_once()


def test_reclaim_memory_calls_malloc_trim_on_linux(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setattr("platform.system", lambda: "Linux")

    mock_libc = type("MockLibc", (), {"malloc_trim": lambda self, x: None})()
    with patch("ctypes.CDLL", return_value=mock_libc) as mock_cdll:
        memory_manager.reclaim_memory()
        mock_cdll.assert_called_once_with("libc.so.6")


def test_reclaim_memory_skips_malloc_trim_on_non_linux(monkeypatch):
    _reset()
    monkeypatch.setenv("RECLAIM_MEMORY_AFTER_CONVERSION", "true")
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    with patch("ctypes.CDLL") as mock_cdll:
        memory_manager.reclaim_memory()
        mock_cdll.assert_not_called()
