import logging
import sys

from app import weasyprint_service_application


def test_main_runs_single_worker(monkeypatch, tmp_path):
    """Test that main runs correctly in single-worker mode."""
    # Set up temporary log directory
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    # Mock command line arguments (single-worker mode, default)
    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999"])

    # Set up fake server
    logger = logging.getLogger("test")

    def fake_start_server_single_worker(port):
        logger.info(f"Fake server started on port {port}")

    monkeypatch.setattr(weasyprint_service_application, "start_server_single_worker", fake_start_server_single_worker)

    # Run main and verify
    weasyprint_service_application.main()

    # Verify log directory was created
    assert log_dir.exists()
    assert any(log_dir.glob("weasyprint-service_*.log"))


def test_main_runs_multi_worker(monkeypatch, tmp_path):
    """Test that main runs correctly in multi-worker mode."""
    # Set up temporary log directory
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    # Mock command line arguments (multi-worker mode)
    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999", "--workers", "4"])

    # Set up fake multi-worker server
    logger = logging.getLogger("test")

    def fake_start_server_multi_worker(port, workers):
        logger.info(f"Fake multi-worker server started on port {port} with {workers} workers")

    monkeypatch.setattr(weasyprint_service_application, "start_server_multi_worker", fake_start_server_multi_worker)

    # Run main and verify
    weasyprint_service_application.main()

    # Verify log directory was created
    assert log_dir.exists()
    assert any(log_dir.glob("weasyprint-service_*.log"))


def test_main_env_overrides_cli_args(monkeypatch, tmp_path):
    """Test that environment variables override command line arguments."""
    # Set up temporary log directory
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    # Set environment variables
    monkeypatch.setenv("PORT", "8888")
    monkeypatch.setenv("WORKERS", "2")

    # Mock command line arguments (should be overridden by env vars)
    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999", "--workers", "1"])

    # Track what was called
    called_with = {}

    def fake_start_server_multi_worker(port, workers):
        called_with["port"] = port
        called_with["workers"] = workers

    monkeypatch.setattr(weasyprint_service_application, "start_server_multi_worker", fake_start_server_multi_worker)

    # Run main
    weasyprint_service_application.main()

    # Verify env vars took precedence
    assert called_with["port"] == 8888
    assert called_with["workers"] == 2


def test_main_workers_one_uses_single_mode(monkeypatch, tmp_path):
    """Test that workers=1 uses single-worker mode."""
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999", "--workers", "1"])

    single_worker_called = False

    def fake_start_server_single_worker(port):
        nonlocal single_worker_called
        single_worker_called = True

    monkeypatch.setattr(weasyprint_service_application, "start_server_single_worker", fake_start_server_single_worker)

    weasyprint_service_application.main()

    assert single_worker_called


def test_main_workers_greater_than_one_uses_multi_mode(monkeypatch, tmp_path):
    """Test that workers>1 uses multi-worker mode."""
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    monkeypatch.setattr(sys, "argv", ["weasyprint_service_application.py", "--port", "9999", "--workers", "3"])

    multi_worker_called = False

    def fake_start_server_multi_worker(port, workers):
        nonlocal multi_worker_called
        multi_worker_called = True
        assert workers == 3

    monkeypatch.setattr(weasyprint_service_application, "start_server_multi_worker", fake_start_server_multi_worker)

    weasyprint_service_application.main()

    assert multi_worker_called


def test_start_server_multi_worker_builds_correct_command(monkeypatch):
    """Test that start_server_multi_worker builds correct gunicorn command."""
    import subprocess

    # Track subprocess.run calls
    commands_run = []

    def fake_subprocess_run(cmd, check=True):  # noqa: ARG001
        commands_run.append(cmd)
        # Return a mock result
        class FakeResult:
            returncode = 0

        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(sys, "exit", lambda code: None)  # Prevent actual exit

    # Call the function
    weasyprint_service_application.start_server_multi_worker(port=9080, workers=4)

    # Verify command was built correctly
    assert len(commands_run) == 1
    cmd = commands_run[0]
    assert cmd[0] == "gunicorn"
    assert cmd[1] == "app.weasyprint_controller:app"
    assert cmd[2] == "--config"
    assert cmd[3] == "gunicorn.conf.py"


def test_start_server_multi_worker_sets_env_vars(monkeypatch):
    """Test that start_server_multi_worker sets PORT and WORKERS env vars."""
    import os
    import subprocess

    def fake_subprocess_run(cmd, check=True):  # noqa: ARG001
        # Verify env vars are set
        assert os.environ.get("PORT") == "8080"
        assert os.environ.get("WORKERS") == "2"

        class FakeResult:
            returncode = 0

        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(sys, "exit", lambda code: None)

    # Call the function
    weasyprint_service_application.start_server_multi_worker(port=8080, workers=2)
