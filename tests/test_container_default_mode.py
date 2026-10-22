"""The image as it is shipped, without SVG_RENDERER: weasysvg draws SVG as vector and no browser runs."""

from __future__ import annotations

import contextlib
import subprocess
import time
from typing import TYPE_CHECKING

import docker
import pymupdf
import pytest
import requests

if TYPE_CHECKING:
    from collections.abc import Iterator

IMAGE_TAG = "weasyprint_service_default_mode_test"
PORT = 9082
SVG_HTML = '<html><body><p>Diagram</p><img src="data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22100%22><rect width=%22200%22 height=%22100%22 fill=%22red%22/></svg>"></body></html>'


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    result = subprocess.run(
        ["docker", "build", "--build-arg", "APP_IMAGE_VERSION=1.0.0", "--tag", IMAGE_TAG, "."],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")

    client = docker.from_env()
    container = client.containers.run(image=IMAGE_TAG, detach=True, ports={"9080": PORT}, init=True, auto_remove=True, labels={"test-suite": "weasyprint-service-default-mode"})
    try:
        for _ in range(60):
            container.reload()
            if container.attrs["State"].get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(1)
        else:
            pytest.fail("The container did not become healthy")
        yield f"http://localhost:{PORT}"
    finally:
        with contextlib.suppress(Exception):
            container.stop()


def test_the_default_mode_is_weasysvg_without_chromium(base_url: str) -> None:
    version = requests.get(f"{base_url}/version", timeout=10).json()

    assert version["svgRenderer"] == "weasysvg"
    assert version["weasysvg"]
    assert version["chromium"] is None
    assert requests.get(f"{base_url}/health", timeout=10).status_code == 200


def test_the_default_mode_draws_svg_as_vector(base_url: str) -> None:
    response = requests.post(f"{base_url}/convert/html", data=SVG_HTML.encode(), headers={"Content-Type": "text/html"}, timeout=60)
    assert response.status_code == 200

    with pymupdf.open(stream=response.content, filetype="pdf") as doc:
        page = doc[0]
        # No image: the SVG is drawn as a form of vector paths, not rasterized to a PNG
        assert page.get_images() == []
        assert page.get_xobjects()
        assert any(drawing["fill"] == (1.0, 0.0, 0.0) for drawing in page.get_drawings())
