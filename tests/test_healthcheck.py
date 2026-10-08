"""Tests for the container healthcheck script."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HEALTHCHECK = Path(__file__).parent.parent / "healthcheck.sh"
PROBE = Path(__file__).parent.parent / "app" / "healthcheck_probe.py"

FAKE_PYTHON = """#!/bin/sh
printf '%s\\n' "$@" > "${PROBE_ARGS_FILE}"
"""


@pytest.fixture
def run_healthcheck(tmp_path: Path):
    """Run the script with python replaced by a recorder, and return its result and the arguments of the probe."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text(FAKE_PYTHON, encoding="utf-8")
    fake_python.chmod(0o755)
    args_file = tmp_path / "probe-args"

    def run(env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        completed = subprocess.run(
            ["/bin/sh", str(HEALTHCHECK)],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "PROBE_ARGS_FILE": str(args_file), **env},
        )
        recorded = args_file.read_text(encoding="utf-8").split() if args_file.exists() else []
        # python -I <probe> PORT [SERVER_CERT [CLIENT_CERT CLIENT_KEY]]: return what the probe receives
        if recorded:
            assert recorded[:2] == ["-I", str(PROBE)]
        return completed, recorded[2:]

    return run


def test_plain_http_by_default(run_healthcheck) -> None:
    completed, args = run_healthcheck({})

    assert completed.returncode == 0
    assert args == ["9080"]


def test_port_is_taken_from_the_environment(run_healthcheck) -> None:
    _, args = run_healthcheck({"PORT": "9999"})

    assert args == ["9999"]


def test_configured_certificate_is_passed_to_the_probe(run_healthcheck) -> None:
    """The probe verifies the server against the certificate the server is configured with."""
    completed, args = run_healthcheck({"TLS_CERT_FILE": "/tls/server.pem"})

    assert completed.returncode == 0
    assert args == ["9080", "/tls/server.pem"]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_certificate_stays_on_http(run_healthcheck, blank: str) -> None:
    """app/tls.py reads a blank value as unset, so the probe has to agree."""
    _, args = run_healthcheck({"TLS_CERT_FILE": blank})

    assert args == ["9080"]


def test_client_certificate_is_passed_to_the_probe(run_healthcheck) -> None:
    completed, args = run_healthcheck(
        {
            "TLS_CERT_FILE": "/tls/server.pem",
            "TLS_HEALTHCHECK_CERT_FILE": "/tls/probe.pem",
            "TLS_HEALTHCHECK_KEY_FILE": "/tls/probe.key",
        }
    )

    assert completed.returncode == 0
    assert args == ["9080", "/tls/server.pem", "/tls/probe.pem", "/tls/probe.key"]


def test_client_certificate_without_tls_is_not_passed(run_healthcheck) -> None:
    """Without TLS there is no handshake to present a client certificate in."""
    _, args = run_healthcheck({"TLS_HEALTHCHECK_CERT_FILE": "/tls/probe.pem", "TLS_HEALTHCHECK_KEY_FILE": "/tls/probe.key"})

    assert args == ["9080"]


@pytest.mark.parametrize("configured", ["TLS_HEALTHCHECK_CERT_FILE", "TLS_HEALTHCHECK_KEY_FILE"])
def test_half_configured_client_certificate_is_reported(run_healthcheck, configured: str) -> None:
    """One half of the pair would fail the handshake with nothing naming the cause."""
    completed, _ = run_healthcheck({"TLS_CERT_FILE": "/tls/server.pem", configured: "/tls/probe"})

    assert completed.returncode == 1
    assert "TLS_HEALTHCHECK_CERT_FILE and TLS_HEALTHCHECK_KEY_FILE" in completed.stderr
