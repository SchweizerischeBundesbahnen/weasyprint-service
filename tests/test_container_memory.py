import logging
import time

import docker
import pytest
import requests
from docker.models.containers import Container

CONTAINER_PORT = 9080
CONVERSION_COUNT = 10


def _generate_heavy_html() -> str:
    """Generate a large HTML document that forces significant memory allocation during PDF rendering."""
    rows = "".join(f"<tr><td>Row {i}</td><td>{'X' * 500}</td><td>{'Y' * 500}</td></tr>" for i in range(3000))
    return f"<html><body><table>{rows}</table></body></html>"


def _get_container_memory_mb(container: Container) -> float:
    """Get current container memory usage in MB via Docker stats API."""
    stats = container.stats(stream=False)
    usage = stats["memory_stats"]["usage"]
    # Subtract cache to get actual working set (if available)
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


def _do_heavy_conversions(base_url: str, count: int) -> None:
    """Send multiple heavy HTML-to-PDF conversion requests."""
    html = _generate_heavy_html()
    session = requests.Session()
    for i in range(count):
        response = session.post(f"{base_url}/convert/html", headers={"Content-Type": "text/html"}, data=html)
        assert response.status_code == 200, f"Conversion {i + 1} failed with status {response.status_code}: {response.text}"
    session.close()


@pytest.fixture(scope="module")
def docker_image():
    """Build the Docker image once for this module."""
    client = docker.from_env()
    image, _ = client.images.build(path=".", tag="weasyprint_service_memory_test", buildargs={"APP_IMAGE_VERSION": "1.0.0"})
    yield client, image


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
        pass


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
        pass


def test_memory_stays_high_without_reclaim(container_reclaim_disabled) -> None:
    """Without reclaim, container memory should grow during conversions and stay high afterwards."""
    container, base_url = container_reclaim_disabled

    baseline_mb = _get_container_memory_mb(container)
    logging.info("Baseline memory (reclaim disabled): %.1f MB", baseline_mb)

    _do_heavy_conversions(base_url, CONVERSION_COUNT)

    # Allow a brief settle period for any async cleanup
    time.sleep(2)

    after_mb = _get_container_memory_mb(container)
    logging.info("After %d conversions (reclaim disabled): %.1f MB (delta: +%.1f MB)", CONVERSION_COUNT, after_mb, after_mb - baseline_mb)

    # Memory should have grown significantly
    assert after_mb > baseline_mb, f"Expected memory to grow after conversions: baseline={baseline_mb:.1f} MB, after={after_mb:.1f} MB"


def test_memory_reclaimed_with_reclaim_enabled(container_reclaim_enabled) -> None:
    """With reclaim enabled, container memory should drop back after conversions."""
    container, base_url = container_reclaim_enabled

    baseline_mb = _get_container_memory_mb(container)
    logging.info("Baseline memory (reclaim enabled): %.1f MB", baseline_mb)

    _do_heavy_conversions(base_url, CONVERSION_COUNT)

    # Allow a brief settle period
    time.sleep(2)

    after_mb = _get_container_memory_mb(container)
    logging.info("After %d conversions (reclaim enabled): %.1f MB (delta: +%.1f MB)", CONVERSION_COUNT, after_mb, after_mb - baseline_mb)

    # Memory may have grown somewhat but should be much closer to baseline than without reclaim.
    # We assert that memory didn't grow by more than 50% over baseline — a generous threshold
    # that still proves reclaim is actively returning memory to the OS.
    growth_ratio = after_mb / baseline_mb
    assert growth_ratio < 1.5, f"Memory grew too much despite reclaim: baseline={baseline_mb:.1f} MB, after={after_mb:.1f} MB (ratio={growth_ratio:.2f})"


def test_reclaim_enabled_uses_less_memory_than_disabled(container_reclaim_disabled, container_reclaim_enabled) -> None:
    """Container with reclaim enabled should use less memory after conversions than without reclaim."""
    container_disabled, base_url_disabled = container_reclaim_disabled
    container_enabled, base_url_enabled = container_reclaim_enabled

    # Both containers have already run conversions from previous tests.
    # Measure current memory of both.
    disabled_mb = _get_container_memory_mb(container_disabled)
    enabled_mb = _get_container_memory_mb(container_enabled)

    logging.info("Memory comparison: disabled=%.1f MB, enabled=%.1f MB (saved: %.1f MB)", disabled_mb, enabled_mb, disabled_mb - enabled_mb)

    assert enabled_mb < disabled_mb, f"Reclaim-enabled container should use less memory: disabled={disabled_mb:.1f} MB, enabled={enabled_mb:.1f} MB"
