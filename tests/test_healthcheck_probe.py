"""Tests for the probe of the container healthcheck, against real local servers."""

from __future__ import annotations

import shutil
import ssl
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import healthcheck_probe


class _Handler(BaseHTTPRequestHandler):
    status = HTTPStatus.OK

    def do_GET(self) -> None:
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args: object) -> None:
        pass


def _serve(status: HTTPStatus, context: ssl.SSLContext | None = None):
    handler = type("Handler", (_Handler,), {"status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if context:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def server():
    servers = []

    def start(status: HTTPStatus = HTTPStatus.OK, context: ssl.SSLContext | None = None) -> int:
        started = _serve(status, context)
        servers.append(started)
        return started.server_address[1]

    yield start
    for started in servers:
        started.shutdown()
        started.server_close()


def _self_signed(tmp_path: Path, name: str) -> tuple[Path, Path]:
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is not available to produce a certificate")
    cert, key = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", f"/CN={name}"],
        check=True,
        capture_output=True,
    )
    return cert, key


def _server_context(tmp_path: Path, client_ca: Path | None = None) -> ssl.SSLContext:
    cert, key = _self_signed(tmp_path, "localhost")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    if client_ca:
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(client_ca)
    return context


def test_healthy_service_passes(server) -> None:
    port = server()

    assert healthcheck_probe.main([f"http://127.0.0.1:{port}/health"]) == 0


def test_unhealthy_service_fails(server, capsys: pytest.CaptureFixture[str]) -> None:
    port = server(HTTPStatus.SERVICE_UNAVAILABLE)

    assert healthcheck_probe.main([f"http://127.0.0.1:{port}/health"]) == 1
    assert "503" in capsys.readouterr().err


def test_service_which_does_not_answer_fails(capsys: pytest.CaptureFixture[str]) -> None:
    # A port which had a server a moment ago and has nothing listening on it now
    closed = _serve(HTTPStatus.OK)
    port = closed.server_address[1]
    closed.shutdown()
    closed.server_close()

    assert healthcheck_probe.main([f"http://127.0.0.1:{port}/health"]) == 1
    assert capsys.readouterr().err


def test_proxy_settings_are_ignored(server, monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy meant for the requests of the service must not carry the probe."""
    port = server()
    for variable in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.setenv(variable, "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)

    assert healthcheck_probe.main([f"http://127.0.0.1:{port}/health"]) == 0


def test_tls_service_passes_without_verifying_its_certificate(server, tmp_path: Path) -> None:
    port = server(context=_server_context(tmp_path))

    assert healthcheck_probe.main([f"https://127.0.0.1:{port}/health"]) == 0


def test_client_certificate_is_presented(server, tmp_path: Path) -> None:
    client_cert, client_key = _self_signed(tmp_path, "probe")
    port = server(context=_server_context(tmp_path, client_ca=client_cert))

    assert healthcheck_probe.main([f"https://127.0.0.1:{port}/health", str(client_cert), str(client_key)]) == 0


def test_server_demanding_a_client_certificate_rejects_the_probe_without_one(server, tmp_path: Path) -> None:
    client_cert, _ = _self_signed(tmp_path, "probe")
    port = server(context=_server_context(tmp_path, client_ca=client_cert))

    assert healthcheck_probe.main([f"https://127.0.0.1:{port}/health"]) == 1


def test_unreadable_client_certificate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = str(tmp_path / "missing.pem")

    assert healthcheck_probe.main(["https://127.0.0.1:1/health", missing, missing]) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://localhost/health", "localhost:9080/health"])
def test_other_schemes_are_refused(url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert healthcheck_probe.main([url]) == 1
    assert "only probes http and https" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["http://localhost/health", "/tls/probe.pem"]])
def test_wrong_arguments_are_reported(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert healthcheck_probe.main(argv) == 2
    assert "Usage" in capsys.readouterr().err


def test_probe_runs_as_a_script(server) -> None:
    """healthcheck.sh runs the file with python -I, outside of the package."""
    port = server()
    probe = Path(healthcheck_probe.__file__)

    completed = subprocess.run([sys.executable, "-I", str(probe), f"http://127.0.0.1:{port}/health"], capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
