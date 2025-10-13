"""
Gunicorn configuration for WeasyPrint service with multi-worker support.

This configuration enables production-grade multi-worker deployment using
Gunicorn as the process manager with Uvicorn workers for async support.

Environment Variables:
    WORKERS: Number of worker processes (default: 1, recommended: CPU cores * 2)
    WORKER_TIMEOUT: Worker timeout in seconds (default: 120)
    GRACEFUL_TIMEOUT: Graceful shutdown timeout in seconds (default: 30)
    KEEP_ALIVE: Keep-alive timeout in seconds (default: 5)
    PORT: Service port (default: 9080)
    LOG_LEVEL: Log level (default: INFO)

Notes:
    - Each worker runs its own ChromiumManager with a dedicated Chromium process
    - Worker class is fixed to uvicorn.workers.UvicornWorker for async FastAPI support
    - Preloading is disabled to ensure each worker has isolated state
"""

import os
from typing import Any

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '9080')}"

# Worker processes
workers = int(os.getenv("WORKERS", "1"))
worker_class = "uvicorn.workers.UvicornWorker"

# Worker timeout (time a worker can handle a request before being killed)
timeout = int(os.getenv("WORKER_TIMEOUT", "120"))

# Graceful timeout (time to wait for workers to finish serving requests before shutdown)
graceful_timeout = int(os.getenv("GRACEFUL_TIMEOUT", "30"))

# Keep-alive (seconds to wait for requests on a Keep-Alive connection)
keepalive = int(os.getenv("KEEP_ALIVE", "5"))

# Logging
loglevel = os.getenv("LOG_LEVEL", "INFO").lower()
accesslog = "-"  # stdout
errorlog = "-"  # stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "weasyprint-service"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (not configured - use reverse proxy like nginx for HTTPS termination)
keyfile = None
certfile = None

# Disable preload_app to ensure each worker has isolated ChromiumManager
# This is critical for proper resource management with ChromiumManager singleton
preload_app = False

# Worker lifecycle hooks


def on_starting(server: Any) -> None:
    """Called just before the master process is initialized."""
    server.log.info("Starting Gunicorn with %d worker(s)", workers)


def when_ready(server: Any) -> None:
    """Called just after the server is started."""
    server.log.info("Gunicorn is ready. Listening on: %s", bind)


def on_reload(server: Any) -> None:
    """Called when configuration is reloaded."""
    server.log.info("Configuration reloaded")


def worker_int(worker: Any) -> None:
    """Called when a worker receives SIGINT or SIGQUIT signal."""
    worker.log.info("Worker %s: received SIGINT/SIGQUIT, shutting down gracefully", worker.pid)


def worker_abort(worker: Any) -> None:
    """Called when a worker receives SIGABRT signal."""
    worker.log.warning("Worker %s: received SIGABRT, aborting", worker.pid)


def pre_fork(server: Any, worker: Any) -> None:
    """Called just before a worker is forked."""
    pass


def post_fork(server: Any, worker: Any) -> None:
    """Called just after a worker has been forked."""
    server.log.info("Worker %s spawned (PID: %s)", worker.age, worker.pid)


def post_worker_init(worker: Any) -> None:
    """Called just after a worker has initialized the application."""
    worker.log.info("Worker %s: application initialized", worker.pid)


def worker_exit(server: Any, worker: Any) -> None:
    """Called just after a worker has been exited."""
    server.log.info("Worker %s exited", worker.pid)


def on_exit(server: Any) -> None:
    """Called just before the master process exits."""
    server.log.info("Shutting down: master process exiting")
