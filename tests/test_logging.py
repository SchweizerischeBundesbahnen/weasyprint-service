import concurrent.futures
import logging
import os
import time
from pathlib import Path

import pytest

from app.weasyprint_service_application import setup_logging


@pytest.fixture(autouse=True)
def cleanup_handlers():
    """Clean up logging handlers before and after each test."""
    # Clean up before test
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    yield

    # Clean up after test
    for handler in root_logger.handlers[:]:
        handler.flush()
        handler.close()
        root_logger.removeHandler(handler)


@pytest.fixture
def log_dir(tmp_path):
    """Create a temporary log directory for testing."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LOG_DIR"] = str(log_dir)
    yield log_dir
    if "LOG_DIR" in os.environ:
        del os.environ["LOG_DIR"]


def wait_for_log_file(log_dir: Path, timeout: float = 1.0) -> Path:
    """Wait for log file to appear and be non-empty."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            log_file = next(log_dir.glob("weasyprint-service_*.log"))
            if log_file.stat().st_size > 0:
                return log_file
        except (StopIteration, FileNotFoundError):
            pass
        time.sleep(0.1)
    raise TimeoutError("Log file not found or empty within timeout")


def test_log_file_creation(log_dir):
    """Test that log file is created in the correct directory."""
    log_file = setup_logging()
    assert log_file.exists()
    assert log_file.parent == log_dir
    assert log_file.name.startswith("weasyprint-service_")
    assert log_file.name.endswith(".log")


def test_log_level_from_env(log_dir):
    """Test that log level is correctly set from environment variable."""
    os.environ["LOG_LEVEL"] = "DEBUG"
    setup_logging()
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    del os.environ["LOG_LEVEL"]


def test_log_message_format(log_dir):
    """Test that log messages are formatted correctly."""
    log_file = setup_logging()
    test_message = "Test log message"
    logging.info(test_message)

    # Ensure handlers are flushed
    for handler in logging.getLogger().handlers:
        handler.flush()

    # Read log content
    log_content = log_file.read_text()
    assert test_message in log_content

    # Check format: timestamp - logger name - log level - message
    log_lines = log_content.splitlines()
    for line in log_lines:
        if test_message in line:
            parts = line.split(" - ")
            assert len(parts) == 4
            assert "root" in parts[1]
            assert "INFO" in parts[2]
            assert test_message in parts[3]


def test_multiple_log_messages(log_dir):
    """Test that multiple log messages are written correctly."""
    log_file = setup_logging()
    messages = [
        (logging.DEBUG, "Debug message"),
        (logging.INFO, "Info message"),
        (logging.WARNING, "Warning message"),
        (logging.ERROR, "Error message"),
        (logging.CRITICAL, "Critical message"),
    ]

    # Write messages
    for level, msg in messages:
        logging.log(level, msg)

    # Ensure handlers are flushed
    for handler in logging.getLogger().handlers:
        handler.flush()

    # Read log content
    log_content = log_file.read_text()

    # Verify each message at INFO or above is present
    for level, msg in messages:
        if level >= logging.INFO:  # Default level is INFO
            assert msg in log_content, f"Message '{msg}' not found in log"


def test_concurrent_logging(log_dir):
    """Test that logging works correctly with concurrent writes."""
    log_file = setup_logging()
    message_count = 100

    def write_log(i):
        logging.info(f"Concurrent message {i}")

    # Write logs concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_log, range(message_count)))  # Force completion

    # Ensure handlers are flushed
    for handler in logging.getLogger().handlers:
        handler.flush()

    # Read log content
    log_content = log_file.read_text()

    # Verify all messages were written
    for i in range(message_count):
        assert f"Concurrent message {i}" in log_content


def test_invalid_log_level(log_dir):
    """Test that invalid log level defaults to INFO."""
    os.environ["LOG_LEVEL"] = "INVALID"
    setup_logging()
    assert logging.getLogger().getEffectiveLevel() == logging.INFO
    del os.environ["LOG_LEVEL"]
