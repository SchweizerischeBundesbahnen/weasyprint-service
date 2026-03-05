import logging
import subprocess
import time
from pathlib import Path

import docker
import pytest
import requests
from docker.models.containers import Container

IMAGE_TAG = "weasyprint_service_memory_test"
HEAVY_HTML_PATH = Path("tests/test-data/html-with-svg-and-png-in-tables.html")


def _get_container_memory_mb(container: Container) -> float:
    """Get current container memory usage in MB via Docker stats API."""
    stats = container.stats(stream=False)
    usage = stats["memory_stats"]["usage"]
    cache = stats["memory_stats"].get("stats", {}).get("cache", 0)
    return (usage - cache) / 1024 / 1024


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


def _convert_html(base_url: str, html: str) -> float:
    """Send a single HTML-to-PDF conversion request. Returns elapsed time in ms."""
    start = time.time()
    response = requests.post(f"{base_url}/convert/html", headers={"Content-Type": "text/html"}, data=html.encode("utf-8"))
    elapsed_ms = (time.time() - start) * 1000
    assert response.status_code == 200, f"Conversion failed: {response.status_code}: {response.text[:500]}"
    return elapsed_ms


@pytest.fixture(scope="module")
def docker_image():
    """Build the Docker image once for this module (via CLI for BuildKit cache support)."""
    client = docker.from_env()
    result = subprocess.run(
        ["docker", "build", "--build-arg", "APP_IMAGE_VERSION=1.0.0", "--tag", IMAGE_TAG, "."],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")
    image = client.images.get(IMAGE_TAG)
    yield client, image


@pytest.fixture(scope="module")
def heavy_html() -> str:
    """Load heavy HTML with embedded SVG and PNG images."""
    return HEAVY_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def container_reclaim_disabled(docker_image):
    """Container with memory reclamation disabled (default behavior)."""
    client, image = docker_image
    host_port = 19080
    container = client.containers.run(
        image=image,
        detach=True,
        name="weasyprint_memory_test_disabled",
        ports={"9080": host_port},
        init=True,
        auto_remove=True,
        labels={"test-suite": "weasyprint-service-memory"},
    )
    _wait_for_healthy(container)
    yield container, f"http://localhost:{host_port}"
    try:
        container.stop()
    except Exception:
        logging.warning("Failed to stop container %s", container.id[:12])


@pytest.fixture(scope="module")
def container_reclaim_enabled(docker_image):
    """Container with memory reclamation enabled."""
    client, image = docker_image
    host_port = 19081
    container = client.containers.run(
        image=image,
        detach=True,
        name="weasyprint_memory_test_enabled",
        ports={"9080": host_port},
        init=True,
        auto_remove=True,
        environment={"RECLAIM_MEMORY_AFTER_CONVERSION": "true"},
        labels={"test-suite": "weasyprint-service-memory"},
    )
    _wait_for_healthy(container)
    yield container, f"http://localhost:{host_port}"
    try:
        container.stop()
    except Exception:
        logging.warning("Failed to stop container %s", container.id[:12])


def test_memory_stays_high_without_reclaim(container_reclaim_disabled, heavy_html) -> None:
    """Without reclaim, container memory should grow after converting a heavy document with images and stay high."""
    container, base_url = container_reclaim_disabled

    baseline_mb = _get_container_memory_mb(container)
    logging.info("Baseline memory (reclaim disabled): %.1f MB", baseline_mb)

    elapsed_ms = _convert_html(base_url, heavy_html)
    logging.info("Conversion time (reclaim disabled): %.0f ms", elapsed_ms)

    time.sleep(2)

    after_mb = _get_container_memory_mb(container)
    growth_mb = after_mb - baseline_mb
    logging.info("After conversion (reclaim disabled): %.1f MB (growth: +%.1f MB)", after_mb, growth_mb)

    assert after_mb > baseline_mb, f"Expected memory to grow: baseline={baseline_mb:.1f} MB, after={after_mb:.1f} MB"


def test_memory_reclaimed_with_reclaim_enabled(container_reclaim_enabled, heavy_html) -> None:
    """With reclaim enabled, container memory should not stay significantly elevated after conversion."""
    container, base_url = container_reclaim_enabled

    baseline_mb = _get_container_memory_mb(container)
    logging.info("Baseline memory (reclaim enabled): %.1f MB", baseline_mb)

    elapsed_ms = _convert_html(base_url, heavy_html)
    logging.info("Conversion time (reclaim enabled): %.0f ms", elapsed_ms)

    time.sleep(2)

    after_mb = _get_container_memory_mb(container)
    growth_mb = after_mb - baseline_mb
    growth_ratio = after_mb / baseline_mb
    logging.info("After conversion (reclaim enabled): %.1f MB (growth: +%.1f MB, ratio: %.2f)", after_mb, growth_mb, growth_ratio)

    # Memory may grow somewhat but should stay within 50% of baseline thanks to gc.collect + malloc_trim
    assert growth_ratio < 1.5, f"Memory grew too much despite reclaim: baseline={baseline_mb:.1f} MB, after={after_mb:.1f} MB (ratio={growth_ratio:.2f})"


def test_reclaim_enabled_uses_less_memory_than_disabled(container_reclaim_disabled, container_reclaim_enabled, heavy_html) -> None:
    """Container with reclaim enabled should use less memory after conversion than without reclaim."""
    container_disabled, base_url_disabled = container_reclaim_disabled
    container_enabled, base_url_enabled = container_reclaim_enabled

    # Run conversions to ensure both containers have processed documents regardless of test execution order
    _convert_html(base_url_disabled, heavy_html)
    _convert_html(base_url_enabled, heavy_html)

    time.sleep(2)

    disabled_mb = _get_container_memory_mb(container_disabled)
    enabled_mb = _get_container_memory_mb(container_enabled)

    logging.info("Memory comparison: disabled=%.1f MB, enabled=%.1f MB (saved: %.1f MB)", disabled_mb, enabled_mb, disabled_mb - enabled_mb)

    assert enabled_mb < disabled_mb, f"Reclaim-enabled container should use less memory: disabled={disabled_mb:.1f} MB, enabled={enabled_mb:.1f} MB"
