"""Tests for the container healthcheck script."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HEALTHCHECK = Path(__file__).parent.parent / "healthcheck.sh"

FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$@" > "${CURL_ARGS_FILE}"
"""


@pytest.fixture
def run_healthcheck(tmp_path: Path):
    """Run the script with curl replaced by a recorder, and return its result and arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(FAKE_CURL, encoding="utf-8")
    fake_curl.chmod(0o755)
    args_file = tmp_path / "curl-args"

    def run(env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        completed = subprocess.run(
            ["/bin/sh", str(HEALTHCHECK)],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "CURL_ARGS_FILE": str(args_file), **env},
        )
        recorded = args_file.read_text(encoding="utf-8").split() if args_file.exists() else []
        return completed, recorded

    return run


def test_plain_http_by_default(run_healthcheck) -> None:
    completed, args = run_healthcheck({})

    assert completed.returncode == 0
    assert args[-1] == "http://localhost:9080/health"
    assert "--insecure" not in args


def test_port_is_taken_from_the_environment(run_healthcheck) -> None:
    _, args = run_healthcheck({"PORT": "9999"})

    assert args[-1] == "http://localhost:9999/health"


def test_configured_certificate_switches_the_scheme(run_healthcheck) -> None:
    completed, args = run_healthcheck({"TLS_CERT_FILE": "/tls/server.pem"})

    assert completed.returncode == 0
    assert args[-1] == "https://localhost:9080/health"
    assert "--insecure" in args


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_certificate_stays_on_http(run_healthcheck, blank: str) -> None:
    """app/tls.py reads a blank value as unset, so the probe has to agree."""
    _, args = run_healthcheck({"TLS_CERT_FILE": blank})

    assert args[-1] == "http://localhost:9080/health"


def test_client_certificate_is_passed_to_curl(run_healthcheck) -> None:
    completed, args = run_healthcheck(
        {
            "TLS_CERT_FILE": "/tls/server.pem",
            "TLS_HEALTHCHECK_CERT_FILE": "/tls/probe.pem",
            "TLS_HEALTHCHECK_KEY_FILE": "/tls/probe.key",
        }
    )

    assert completed.returncode == 0
    assert "--cert" in args
    assert "/tls/probe.pem" in args
    assert "--key" in args
    assert "/tls/probe.key" in args


@pytest.mark.parametrize("configured", ["TLS_HEALTHCHECK_CERT_FILE", "TLS_HEALTHCHECK_KEY_FILE"])
def test_half_configured_client_certificate_is_reported(run_healthcheck, configured: str) -> None:
    """One half of the pair would fail the handshake with nothing naming the cause."""
    completed, _ = run_healthcheck({"TLS_CERT_FILE": "/tls/server.pem", configured: "/tls/probe"})

    assert completed.returncode == 1
    assert "TLS_HEALTHCHECK_CERT_FILE and TLS_HEALTHCHECK_KEY_FILE" in completed.stderr
