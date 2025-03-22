import logging
import sys

from app import weasyprint_service_application


def test_main_runs(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999"])

    logger = logging.getLogger("test")

    def fake_start_server(port):
        logger.info(f"Fake server started on port {port}")

    monkeypatch.setattr(weasyprint_service_application.weasyprint_controller, "start_server", fake_start_server)

    weasyprint_service_application.main()
