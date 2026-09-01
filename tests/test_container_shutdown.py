"""Container shutdown tests: "docker stop" has to reach the service as SIGTERM."""

import contextlib
import logging
import subprocess
import time

import docker
import pytest
from docker.models.containers import Container

logger = logging.getLogger(__name__)

IMAGE_TAG = "weasyprint_service_shutdown_test"
CONTAINER_NAME = "weasyprint_service_shutdown_test"
# Docker sends SIGKILL after this many seconds. The service has to be gone well before.
STOP_TIMEOUT_SECONDS = 30
MAX_SHUTDOWN_SECONDS = 20
# uvicorn re-raises the signal it captured once the shutdown is done, so a service stopped by
# SIGTERM reports 143 (128 + 15). 0 covers a uvicorn version which returns instead.
EXPECTED_EXIT_CODES = (0, 143)


def _wait_for_healthy(container: Container, max_wait: int = 120) -> None:
    start = time.time()
    while time.time() - start < max_wait:
        container.reload()
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")
        if health == "healthy":
            return
        time.sleep(1)
    logs = container.logs().decode("utf-8")
    raise TimeoutError(f"Container not healthy within {max_wait}s. Logs:\n{logs}")


@pytest.fixture(scope="module")
def stopped_container():
    """
    Build and start the image, wait until it is healthy, then stop it with SIGTERM.

    The container keeps its logs after the stop (no auto_remove), so the test can
    read what the service did while it shut down.

    Yields:
        tuple: The stopped container and the seconds the stop took.
    """
    client = docker.from_env()

    # A container of an interrupted run holds the name, and the run below would fail on it.
    with contextlib.suppress(docker.errors.NotFound):
        client.containers.get(CONTAINER_NAME).remove(force=True)

    result = subprocess.run(
        ["docker", "build", "--build-arg", "APP_IMAGE_VERSION=1.0.0", "--tag", IMAGE_TAG, "."],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")

    container = client.containers.run(
        image=IMAGE_TAG,
        detach=True,
        name=CONTAINER_NAME,
        # No port is published: the test drives the container through Docker only, and the
        # health probe runs inside it. This keeps the test off a possibly busy host port.
        init=True,
        auto_remove=False,
        labels={"test-suite": "weasyprint-service-shutdown"},
    )
    try:
        _wait_for_healthy(container)

        start = time.time()
        container.stop(timeout=STOP_TIMEOUT_SECONDS)
        elapsed = time.time() - start
        logger.info("Container stopped in %.1f s", elapsed)

        yield container, elapsed
    finally:
        # Teardown is best effort. The image belongs to this test alone, so it goes too.
        try:
            container.remove(force=True)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to remove container %s", container.id[:12])
        try:
            client.images.remove(IMAGE_TAG, force=True)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to remove image %s", IMAGE_TAG)


def test_sigterm_shuts_the_service_down_gracefully(stopped_container) -> None:
    """SIGTERM runs the shutdown hooks: metrics server and Chromium browser are closed."""
    container, _ = stopped_container
    logs = container.logs().decode("utf-8")

    expected_patterns = [
        # uvicorn reports the stop through the root logger, the service reports the rest
        "Shutting down",
        "Waiting for application shutdown",
        "Application shutdown complete",
        "Finished server process",
        "Metrics server stopped",
        "Stopping background health monitoring...",
        "Background health monitoring stopped",
        "Stopping Chromium browser...",
        "Chromium browser stopped successfully",
        "Service shutdown complete",
    ]
    for pattern in expected_patterns:
        assert pattern in logs, f"Expected shutdown log pattern not found: '{pattern}'\nLogs:\n{logs}"


def test_sigterm_stops_the_container_before_the_kill_timeout(stopped_container) -> None:
    """The stop completes on SIGTERM, so Docker never has to fall back to SIGKILL."""
    container, elapsed = stopped_container

    assert elapsed < MAX_SHUTDOWN_SECONDS, f"Container took {elapsed:.1f}s to stop, expected less than {MAX_SHUTDOWN_SECONDS}s"

    container.reload()
    exit_code = container.attrs["State"]["ExitCode"]
    assert exit_code in EXPECTED_EXIT_CODES, f"Unexpected exit code {exit_code}\nLogs:\n{container.logs().decode('utf-8')}"
