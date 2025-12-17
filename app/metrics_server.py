"""
Dedicated metrics server for Prometheus metrics endpoint.

This module provides a separate FastAPI application serving only the /metrics
endpoint on a dedicated port for security purposes. This allows network-level
isolation between the main application API and the metrics endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.chromium_manager import ChromiumManager, get_chromium_manager
from app.prometheus_metrics import update_gauges_from_chromium_manager

logger = logging.getLogger(__name__)

# Port constants
MIN_VALID_PORT = 1024
MAX_VALID_PORT = 65535
DEFAULT_METRICS_PORT = 9180
STARTUP_TIMEOUT_SECONDS = 10.0

# Minimal FastAPI app for metrics only
metrics_app = FastAPI(
    title="WeasyPrint Metrics",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@metrics_app.get("/metrics")
async def metrics(chromium_manager: Annotated[ChromiumManager, Depends(get_chromium_manager)]) -> Response:
    """
    Expose Prometheus metrics endpoint.

    This endpoint returns metrics in Prometheus text format, including:
    - Automatic FastAPI request metrics (duration, in-progress, total) from prometheus-fastapi-instrumentator
    - Custom ChromiumManager metrics (conversions, failures, resource usage)
    - System metrics (CPU, memory)

    The metrics are automatically scraped by Prometheus for monitoring and alerting.

    Note: Counters are incremented when events occur. This endpoint only updates gauges
    to reflect current state (CPU, memory, queue size, etc.).
    """
    update_gauges_from_chromium_manager(chromium_manager)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def get_metrics_port() -> int:
    """
    Get metrics server port from environment variable.

    Returns:
        Port number from METRICS_PORT env var (default: 9180).
        Falls back to default if invalid value provided.
    """
    port_str = os.environ.get("METRICS_PORT", str(DEFAULT_METRICS_PORT))
    try:
        port = int(port_str)
        if not (MIN_VALID_PORT <= port <= MAX_VALID_PORT):
            logger.warning("METRICS_PORT must be between %d and %d, using default: %d", MIN_VALID_PORT, MAX_VALID_PORT, DEFAULT_METRICS_PORT)
            return DEFAULT_METRICS_PORT
        return port
    except ValueError:
        logger.warning("Invalid METRICS_PORT value '%s', using default: %d", port_str, DEFAULT_METRICS_PORT)
        return DEFAULT_METRICS_PORT


def is_metrics_server_enabled() -> bool:
    """
    Check if metrics server is enabled.

    Returns:
        True if METRICS_SERVER_ENABLED is not set or set to a truthy value.
    """
    env_value = os.environ.get("METRICS_SERVER_ENABLED", "true")
    return env_value.lower() in ("true", "1", "yes", "on")


class MetricsServer:
    """
    Manages the dedicated metrics server lifecycle.

    This class handles starting and stopping a uvicorn server that serves
    only the /metrics endpoint on a dedicated port.
    """

    def __init__(self, port: int = DEFAULT_METRICS_PORT) -> None:
        """
        Initialize the metrics server.

        Args:
            port: Port to listen on (default: 9180)
        """
        self.port = port
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        """Start the metrics server in the background."""
        if self._started:
            logger.warning("Metrics server already started")
            return

        config = uvicorn.Config(
            app=metrics_app,
            host="",
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())

        # Wait for server to be ready before returning (with timeout)
        start_time = asyncio.get_event_loop().time()
        while not self._server.started:
            if asyncio.get_event_loop().time() - start_time > STARTUP_TIMEOUT_SECONDS:
                logger.error("Metrics server failed to start within %s seconds", STARTUP_TIMEOUT_SECONDS)
                await self.stop()
                raise TimeoutError(f"Metrics server failed to start within {STARTUP_TIMEOUT_SECONDS} seconds")
            await asyncio.sleep(0.01)

        self._started = True
        logger.info("Metrics server started on port %d", self.port)

    async def stop(self) -> None:
        """Stop the metrics server."""
        if not self._started:
            return

        if self._server:
            self._server.should_exit = True

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()
                # Await cancelled task to ensure proper cleanup (will raise CancelledError)
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

        self._started = False
        logger.info("Metrics server stopped")

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._started
