"""Visio drawings in the image as it is shipped: weasyvsdx draws them as vector through libvisio.

Without vsd2xhtml the service leaves Visio images out and only logs a warning, so an image whose
libvisio does not run passes every other test. This one draws a drawing for real.
"""

import base64
import contextlib
import logging
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import pymupdf
import pytest
import requests
from docker.models.containers import Container

logger = logging.getLogger(__name__)

IMAGE_TAG = "weasyprint_service_vsdx_test"
CONTAINER_NAME = "weasyprint_service_vsdx_test"

# A drawing of Apache POI, see tests/test-data/vsdx/README.md
DRAWING = Path("tests/test-data/vsdx/apache-poi-test.vsdx")
# The header bar of the drawing, as Visio fills it
HEADER_RGB = (0x41, 0x71, 0x9C)


def _wait_for_healthy(container: Container, max_wait: int = 120) -> None:
    start = time.time()
    while time.time() - start < max_wait:
        container.reload()
        if container.attrs.get("State", {}).get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(1)
    raise TimeoutError(f"Container not healthy within {max_wait}s. Logs:\n{container.logs().decode('utf-8')}")


@pytest.fixture(scope="module")
def vsdx_image() -> Iterator[str]:
    """Build the image once for the tests of both SVG renderers."""
    result = subprocess.run(
        ["docker", "build", "--build-arg", "APP_IMAGE_VERSION=1.0.0", "--tag", IMAGE_TAG, "."],
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")
    try:
        yield IMAGE_TAG
    finally:
        # The image belongs to this test alone, so it goes too
        try:
            docker.from_env().images.remove(IMAGE_TAG, force=True)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to remove image %s", IMAGE_TAG)


# weasysvg draws the text of a drawing in both modes: wholly by default, its foreignObject alone with chromium
@pytest.fixture(scope="module", params=["weasysvg", "chromium"])
def vsdx_container(request: pytest.FixtureRequest, vsdx_image: str) -> Iterator[tuple[Container, str]]:
    """Start the image with one SVG renderer, on a free host port."""
    client = docker.from_env()
    name = f"{CONTAINER_NAME}_{request.param}"
    # A container of an interrupted run holds the name, and the run below would fail on it.
    with contextlib.suppress(docker.errors.NotFound):
        client.containers.get(name).remove(force=True)

    # Docker picks the host port, so the test never collides with a service already running
    container = client.containers.run(image=vsdx_image, detach=True, name=name, init=True, ports={"9080/tcp": None}, environment={"SVG_RENDERER": request.param})
    try:
        _wait_for_healthy(container)
        container.reload()
        host_port = container.ports["9080/tcp"][0]["HostPort"]
        yield container, f"http://localhost:{host_port}"
    finally:
        # Teardown is best effort
        try:
            container.remove(force=True)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to remove container %s", container.id[:12])


def test_version_names_weasyvsdx_and_libvisio(vsdx_container: tuple[Container, str]) -> None:
    """The image runs weasyvsdx with libvisio 0.1.7 of trixie."""
    _, base_url = vsdx_container
    version = requests.get(f"{base_url}/version", timeout=10).json()

    assert version["weasyvsdx"]
    assert version["libvisio"] == "0.1.7"


def test_vsdx_is_drawn_as_vector(vsdx_container: tuple[Container, str]) -> None:
    """The VSDX image arrives in the PDF as the vector paths and the text of the drawing."""
    container, base_url = vsdx_container
    data_url = "data:application/vnd.ms-visio.drawing;base64," + base64.b64encode(DRAWING.read_bytes()).decode("ascii")
    html = f'<html><head><meta charset="utf-8"></head><body><img src="{data_url}"/></body></html>'

    response = requests.post(f"{base_url}/convert/html", data=html.encode("utf-8"), headers={"Content-Type": "text/html"}, timeout=120)
    assert response.status_code == 200, response.text[:500]

    logs = container.logs().decode("utf-8")
    assert "vsd2xhtml not found" not in logs, f"The image has no libvisio-tools:\n{logs}"

    with pymupdf.open(stream=response.content, filetype="pdf") as document:
        page = document[0]
        # No image: the drawing is drawn as vector paths, not rasterized to a PNG
        assert page.get_images() == []
        fills = {tuple(round(channel * 255) for channel in drawing["fill"]) for drawing in page.get_drawings() if drawing["fill"]}
        text = page.get_text()
    assert HEADER_RGB in fills, f"The header bar of the drawing is missing, fills: {sorted(fills)}"
    assert "This is a test." in text
