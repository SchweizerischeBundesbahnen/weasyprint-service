import logging
import sys

import pytest

from app import weasyprint_service_application


def test_main_runs(monkeypatch, tmp_path):
    """Test that main runs correctly with mocked dependencies."""
    # Set up temporary log directory
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    # Mock command line arguments
    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999"])

    # Set up fake server
    logger = logging.getLogger("test")

    def fake_start_server(port):
        logger.info(f"Fake server started on port {port}")

    monkeypatch.setattr(weasyprint_service_application, "start_server", fake_start_server)

    # Run main and verify
    weasyprint_service_application.main()

    # Verify log directory was created
    assert log_dir.exists()
    assert any(log_dir.glob("weasyprint-service_*.log"))


def test_main_reports_a_disabled_metrics_server(monkeypatch, tmp_path):
    """With the metrics server switched off, main says so instead of naming a port."""
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("METRICS_SERVER_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999"])
    monkeypatch.setattr(weasyprint_service_application, "start_server", lambda port: None)

    weasyprint_service_application.main()

    # setup_logging reconfigures the root logger, so the log file is the record.
    logged = "".join(path.read_text(encoding="utf-8") for path in log_dir.glob("weasyprint-service_*.log"))
    assert "Metrics server disabled" in logged


def test_graceful_shutdown_timeout_defaults(monkeypatch):
    """Without the variable the timeout falls back to the default."""
    monkeypatch.delenv("GRACEFUL_SHUTDOWN_TIMEOUT", raising=False)

    assert weasyprint_service_application.get_graceful_shutdown_timeout() == weasyprint_service_application.DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT


def test_graceful_shutdown_timeout_reads_the_variable(monkeypatch):
    """A valid value is used as is."""
    monkeypatch.setenv("GRACEFUL_SHUTDOWN_TIMEOUT", "45")

    assert weasyprint_service_application.get_graceful_shutdown_timeout() == 45


@pytest.mark.parametrize("value", ["not-a-number", "0", "301"])
def test_graceful_shutdown_timeout_rejects_bad_values(monkeypatch, value):
    """An invalid or out of range value falls back to the default."""
    monkeypatch.setenv("GRACEFUL_SHUTDOWN_TIMEOUT", value)

    assert weasyprint_service_application.get_graceful_shutdown_timeout() == weasyprint_service_application.DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT


def test_start_server_passes_the_graceful_shutdown_timeout(monkeypatch):
    """start_server hands the timeout to uvicorn, which applies it on SIGTERM."""
    monkeypatch.setenv("GRACEFUL_SHUTDOWN_TIMEOUT", "12")
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(weasyprint_service_application.uvicorn, "run", fake_run)

    weasyprint_service_application.start_server(9999)

    assert captured["timeout_graceful_shutdown"] == 12
    assert captured["port"] == 9999
