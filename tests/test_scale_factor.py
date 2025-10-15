from fastapi.testclient import TestClient

from app import weasyprint_controller as wc
from app.svg_processor import SvgProcessor
from app.weasyprint_controller import app


class DummySvgProcessor:
    def __init__(self, device_scale_factor=None, **kwargs):  # type: ignore[no-untyped-def]
        # capture the passed value for assertions
        DummySvgProcessor.last_device_scale_factor = device_scale_factor

    async def process_svg(self, parsed_html):  # type: ignore[no-untyped-def]
        return parsed_html


def test_render_options_scale_factor_query_is_passed(monkeypatch):
    # Ensure predictable environment
    monkeypatch.delenv("DEVICE_SCALE_FACTOR", raising=False)

    # Patch SvgProcessor to our dummy to capture the passed value
    monkeypatch.setattr(wc, "SvgProcessor", DummySvgProcessor)

    with TestClient(app) as client:
        res = client.post(
            "/convert/html?base_url=/&scale_factor=2.5",
            content='<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>',
        )
        assert res.status_code == 200

    assert getattr(DummySvgProcessor, "last_device_scale_factor", None) == 2.5


def test_render_options_scale_factor_defaults_to_none_when_missing(monkeypatch):
    # Set env, but since controller passes None when missing, our dummy should receive None
    monkeypatch.setenv("DEVICE_SCALE_FACTOR", "1.7")

    monkeypatch.setattr(wc, "SvgProcessor", DummySvgProcessor)

    with TestClient(app) as client:
        res = client.post(
            "/convert/html?base_url=/",
            content='<img src="data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjIwMHB4IiB3aWR0aD0iMTAwcHgiPC9zdmc+"/>',
        )
        assert res.status_code == 200

    # None means SvgProcessor should read from env internally (verified by separate unit tests)
    assert getattr(DummySvgProcessor, "last_device_scale_factor", "__missing__") is None


def test_svg_processor_uses_env_scale_factor(monkeypatch):
    # Ensure env is set and no explicit override is provided
    monkeypatch.setenv("DEVICE_SCALE_FACTOR", "2.0")

    sp = SvgProcessor(device_scale_factor=None)
    # Device scale factor should not affect layout unit conversion
    assert sp.get_px_conversion_ratio(None) == 1.0
    # But it should be stored and used for rasterization (Chromium flag)
    assert sp.device_scale_factor == 2.0


def test_svg_processor_explicit_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("DEVICE_SCALE_FACTOR", "2.0")

    sp = SvgProcessor(device_scale_factor=3.0)
    assert sp.get_px_conversion_ratio(None) == 1.0
    assert sp.device_scale_factor == 3.0
