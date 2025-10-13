"""Tests for gunicorn configuration."""

import importlib.util
import os
from pathlib import Path


def test_gunicorn_config_defaults():
    """Test that gunicorn config has correct default values."""
    # Clear environment variables
    for env_var in ["WORKERS", "PORT", "WORKER_TIMEOUT", "GRACEFUL_TIMEOUT", "KEEP_ALIVE", "LOG_LEVEL"]:
        if env_var in os.environ:
            del os.environ[env_var]

    # Load gunicorn config as module
    config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_config", config_path)
    assert spec is not None
    assert spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    # Check defaults
    assert config.bind == "0.0.0.0:9080"
    assert config.workers == 1
    assert config.worker_class == "uvicorn.workers.UvicornWorker"
    assert config.timeout == 120
    assert config.graceful_timeout == 30
    assert config.keepalive == 5
    assert config.loglevel == "info"
    assert config.preload_app is False


def test_gunicorn_config_from_env():
    """Test that gunicorn config reads from environment variables."""
    # Set environment variables
    os.environ["WORKERS"] = "4"
    os.environ["PORT"] = "8080"
    os.environ["WORKER_TIMEOUT"] = "60"
    os.environ["GRACEFUL_TIMEOUT"] = "15"
    os.environ["KEEP_ALIVE"] = "10"
    os.environ["LOG_LEVEL"] = "DEBUG"

    try:
        # Load gunicorn config as module
        config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
        spec = importlib.util.spec_from_file_location("gunicorn_config_env", config_path)
        assert spec is not None
        assert spec.loader is not None
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)

        # Check environment values
        assert config.bind == "0.0.0.0:8080"
        assert config.workers == 4
        assert config.timeout == 60
        assert config.graceful_timeout == 15
        assert config.keepalive == 10
        assert config.loglevel == "debug"

    finally:
        # Cleanup
        for env_var in ["WORKERS", "PORT", "WORKER_TIMEOUT", "GRACEFUL_TIMEOUT", "KEEP_ALIVE", "LOG_LEVEL"]:
            if env_var in os.environ:
                del os.environ[env_var]


def test_gunicorn_config_worker_class():
    """Test that worker class is fixed to UvicornWorker."""
    config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_config_worker", config_path)
    assert spec is not None
    assert spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    # Worker class must be UvicornWorker for async FastAPI support
    assert config.worker_class == "uvicorn.workers.UvicornWorker"


def test_gunicorn_config_preload_disabled():
    """Test that preload_app is disabled for isolated worker state."""
    config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_config_preload", config_path)
    assert spec is not None
    assert spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    # preload_app must be False to ensure each worker has isolated ChromiumManager
    assert config.preload_app is False


def test_gunicorn_config_hooks_exist():
    """Test that gunicorn lifecycle hooks are defined."""
    config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_config_hooks", config_path)
    assert spec is not None
    assert spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    # Check that important hooks are defined
    assert hasattr(config, "on_starting")
    assert callable(config.on_starting)
    assert hasattr(config, "when_ready")
    assert callable(config.when_ready)
    assert hasattr(config, "worker_int")
    assert callable(config.worker_int)
    assert hasattr(config, "post_fork")
    assert callable(config.post_fork)
    assert hasattr(config, "worker_exit")
    assert callable(config.worker_exit)
    assert hasattr(config, "on_exit")
    assert callable(config.on_exit)


def test_gunicorn_config_logging_setup():
    """Test that logging is configured correctly."""
    config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_config_logging", config_path)
    assert spec is not None
    assert spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    # Check logging configuration
    assert config.accesslog == "-"  # stdout
    assert config.errorlog == "-"  # stderr
    assert hasattr(config, "access_log_format")
    assert "%(h)s" in config.access_log_format  # remote address
    assert "%(r)s" in config.access_log_format  # request line
    assert "%(s)s" in config.access_log_format  # status code


def test_gunicorn_config_process_naming():
    """Test that process naming is configured."""
    config_path = Path(__file__).parent.parent / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_config_naming", config_path)
    assert spec is not None
    assert spec.loader is not None
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    # Check process naming
    assert config.proc_name == "weasyprint-service"
