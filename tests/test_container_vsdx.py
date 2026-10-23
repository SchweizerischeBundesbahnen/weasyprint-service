"""VSDX conversion in an image built with ENABLE_VSDX_SUPPORT=true.

Without LibreOffice the service leaves a VSDX image as it is and only logs a warning, so an image
whose LibreOffice does not start passes every other test. This one converts a drawing for real.
"""

import base64
import contextlib
import io
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
from PIL import Image

logger = logging.getLogger(__name__)

IMAGE_TAG = "weasyprint_service_vsdx_test"
CONTAINER_NAME = "weasyprint_service_vsdx_test"

# A drawing of Apache POI, see tests/test-data/vsdx/README.md
DRAWING = Path("tests/test-data/vsdx/apache-poi-test.vsdx")
# The header bar of the drawing, the same in LibreOffice 25.2 and 26.8
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
def vsdx_container() -> Iterator[tuple[Container, str]]:
    """Build the image with LibreOffice and start it on a free host port."""
    client = docker.from_env()
    # A container of an interrupted run holds the name, and the run below would fail on it.
    with contextlib.suppress(docker.errors.NotFound):
        client.containers.get(CONTAINER_NAME).remove(force=True)

    result = subprocess.run(
        ["docker", "build", "--build-arg", "APP_IMAGE_VERSION=1.0.0", "--build-arg", "ENABLE_VSDX_SUPPORT=true", "--tag", IMAGE_TAG, "."],
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")

    # Docker picks the host port, so the test never collides with a service already running
    container = client.containers.run(image=IMAGE_TAG, detach=True, name=CONTAINER_NAME, init=True, ports={"9080/tcp": None})
    try:
        _wait_for_healthy(container)
        container.reload()
        host_port = container.ports["9080/tcp"][0]["HostPort"]
        yield container, f"http://localhost:{host_port}"
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


def test_vsdx_is_converted_to_an_image_of_the_drawing(vsdx_container: tuple[Container, str]) -> None:
    """The VSDX image arrives in the PDF as a picture of the drawing, drawn by LibreOffice."""
    container, base_url = vsdx_container
    data_url = "data:application/vnd.ms-visio.drawing;base64," + base64.b64encode(DRAWING.read_bytes()).decode("ascii")
    html = f'<html><head><meta charset="utf-8"></head><body><img src="{data_url}"/></body></html>'

    response = requests.post(f"{base_url}/convert/html", data=html.encode("utf-8"), headers={"Content-Type": "text/html"}, timeout=120)
    assert response.status_code == 200, response.text[:500]

    logs = container.logs().decode("utf-8")
    assert "LibreOffice not available" not in logs, f"The image was built with VSDX support, but LibreOffice does not run:\n{logs}"
    assert "Converted 1 VSDX data URLs to PNG" in logs

    with pymupdf.open(stream=response.content, filetype="pdf") as document:
        images = [document.extract_image(xref) for page in document for xref, *_ in page.get_images(full=True)]
    assert len(images) == 1, f"Expected the drawing as one image, found {len(images)}"
    picture = Image.open(io.BytesIO(images[0]["image"])).convert("RGB")
    assert HEADER_RGB in {color for _, color in picture.getcolors(maxcolors=picture.width * picture.height)}, "The header bar of the drawing is missing"
