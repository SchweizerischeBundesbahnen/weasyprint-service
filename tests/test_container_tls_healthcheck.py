"""Container tests of the healthcheck over TLS: the image reports its health the way a client of it sees it."""

from __future__ import annotations

import contextlib
import subprocess
import time
from typing import TYPE_CHECKING

import docker
import pytest

from tests.tls_certificates import Pki

if TYPE_CHECKING:
    from pathlib import Path

    from docker.models.containers import Container

IMAGE_TAG = "weasyprint_service_tls_healthcheck_test"
CONTAINER_NAME = "weasyprint_service_tls_healthcheck_test"
TLS_DIR = "/opt/weasyprint/tls"
# The healthcheck starts after 10 s and gives up after 3 failures 5 s apart
MAX_WAIT_SECONDS = 120


@pytest.fixture(scope="module")
def image() -> str:
    result = subprocess.run(
        ["docker", "build", "--build-arg", "APP_IMAGE_VERSION=1.0.0", "--tag", IMAGE_TAG, "."],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")
    return IMAGE_TAG


@pytest.fixture
def certificates(tmp_path: Path) -> tuple[Pki, Path]:
    directory = tmp_path / "tls"
    directory.mkdir()
    return Pki(directory), directory


@pytest.fixture
def run_container(image: str):
    client = docker.from_env()
    started: list[Container] = []

    def run(directory: Path, environment: dict[str, str]) -> Container:
        # The service runs as uid 1000, and the files belong to whoever runs the tests
        directory.chmod(0o755)
        for file in directory.iterdir():
            file.chmod(0o644)
        with contextlib.suppress(docker.errors.NotFound):
            client.containers.get(CONTAINER_NAME).remove(force=True)
        container = client.containers.run(
            image=image,
            detach=True,
            name=CONTAINER_NAME,
            # No port is published: the healthcheck runs inside the container
            init=True,
            environment=environment,
            volumes={str(directory): {"bind": TLS_DIR, "mode": "ro"}},
            labels={"test-suite": "weasyprint-service-tls-healthcheck"},
        )
        started.append(container)
        return container

    yield run
    for container in started:
        with contextlib.suppress(docker.errors.NotFound):
            container.remove(force=True)


def _health_after_start(container: Container) -> tuple[str, str]:
    """Wait for the first verdict of the healthcheck. Return it and the output of the last probe."""
    start = time.time()
    while time.time() - start < MAX_WAIT_SECONDS:
        container.reload()
        health = container.attrs.get("State", {}).get("Health", {})
        if health.get("Status") in ("healthy", "unhealthy"):
            log = health.get("Log") or [{}]
            return health["Status"], log[-1].get("Output", "")
        time.sleep(1)
    logs = container.logs().decode("utf-8")
    raise TimeoutError(f"The healthcheck reached no verdict within {MAX_WAIT_SECONDS}s. Logs:\n{logs}")


def _server(certificates: tuple[Pki, Path], cert_name: str = "server.pem", key_name: str = "server.key") -> dict[str, str]:
    return {"TLS_CERT_FILE": f"{TLS_DIR}/{cert_name}", "TLS_KEY_FILE": f"{TLS_DIR}/{key_name}"}


def test_tls_service_is_healthy(certificates: tuple[Pki, Path], run_container) -> None:
    pki, directory = certificates
    pki.self_signed("server", "DNS:weasyprint.example.com")

    container = run_container(directory, _server(certificates))

    assert _health_after_start(container)[0] == "healthy"


def test_service_requiring_client_certificates_is_healthy_with_one_for_the_probe(certificates: tuple[Pki, Path], run_container) -> None:
    pki, directory = certificates
    pki.self_signed("server", "DNS:weasyprint.example.com")
    pki.self_signed("probe", extended_key_usage="clientAuth")

    container = run_container(
        directory,
        {
            **_server(certificates),
            "TLS_CLIENT_AUTH": "required",
            "TLS_CLIENT_CA_FILE": f"{TLS_DIR}/probe.pem",
            "TLS_HEALTHCHECK_CERT_FILE": f"{TLS_DIR}/probe.pem",
            "TLS_HEALTHCHECK_KEY_FILE": f"{TLS_DIR}/probe.key",
        },
    )

    assert _health_after_start(container)[0] == "healthy"


def test_service_with_an_expired_certificate_is_unhealthy(certificates: tuple[Pki, Path], run_container) -> None:
    """The service starts, but no client could connect to it, and the healthcheck says so."""
    pki, directory = certificates
    pki.expired("server", "DNS:weasyprint.example.com")

    container = run_container(directory, _server(certificates))

    status, output = _health_after_start(container)
    assert status == "unhealthy"
    assert "expired" in output
