"""Tests for the probe of the container healthcheck, against real local servers and real certificates."""

from __future__ import annotations

import ssl
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import healthcheck_probe
from tests.tls_certificates import Pki


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


@pytest.fixture
def pki(tmp_path: Path) -> Pki:
    return Pki(tmp_path)


def _server_context(cert: Path, key: Path, client_ca: Path | None = None) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    if client_ca:
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(client_ca)
    return context


# Plain HTTP


def test_healthy_service_passes(server) -> None:
    port = server()

    assert healthcheck_probe.main([str(port)]) == 0


def test_unhealthy_service_fails(server, capsys: pytest.CaptureFixture[str]) -> None:
    port = server(HTTPStatus.SERVICE_UNAVAILABLE)

    assert healthcheck_probe.main([str(port)]) == 1
    assert "503" in capsys.readouterr().err


def test_service_which_does_not_answer_fails(capsys: pytest.CaptureFixture[str]) -> None:
    # A port which had a server a moment ago and has nothing listening on it now
    closed = _serve(HTTPStatus.OK)
    port = closed.server_address[1]
    closed.shutdown()
    closed.server_close()

    assert healthcheck_probe.main([str(port)]) == 1
    assert capsys.readouterr().err


def test_proxy_settings_are_ignored(server, monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy meant for the requests of the service must not carry the probe."""
    port = server()
    for variable in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.setenv(variable, "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)

    assert healthcheck_probe.main([str(port)]) == 0


# TLS: the probe verifies the server against the certificate the server is configured with


@pytest.mark.parametrize(
    "san",
    [
        "DNS:weasyprint.example.com",
        "DNS:weasyprint.example.com,DNS:pdf.example.com",
        "DNS:*.example.com",  # a wildcard is checked with a concrete label
        "IP:10.1.2.3",  # an address the loopback interface does not have: the name is checked, not dialled
        "IP:10.1.2.3,DNS:weasyprint.example.com",
    ],
)
def test_tls_service_passes_with_a_verified_certificate(server, pki: Pki, san: str) -> None:
    cert, key = pki.self_signed("server", san)
    port = server(context=_server_context(cert, key))

    assert healthcheck_probe.main([str(port), str(cert)]) == 0


def test_certificate_signed_by_an_authority_passes_without_the_authority(server, pki: Pki) -> None:
    """The certificate of the server is trusted on its own: the image needs no CA for the probe."""
    cert, key = pki.signed("server", "DNS:pdf.example.com", pki.certificate_authority())
    port = server(context=_server_context(cert, key))

    assert healthcheck_probe.main([str(port), str(cert)]) == 0


def test_chain_file_passes(server, pki: Pki, tmp_path: Path) -> None:
    """A file with the certificate of the server first and its chain after it, as servers are configured."""
    authority = pki.certificate_authority()
    cert, key = pki.signed("server", "DNS:pdf.example.com", authority)
    chain = tmp_path / "chain.pem"
    chain.write_text(cert.read_text(encoding="ascii") + authority[0].read_text(encoding="ascii"), encoding="ascii")
    port = server(context=_server_context(chain, key))

    assert healthcheck_probe.main([str(port), str(chain)]) == 0


def test_text_around_the_certificate_is_ignored(server, pki: Pki, tmp_path: Path) -> None:
    """openssl pkcs12 writes attributes before each block, and a friendly name may be no ASCII. OpenSSL skips them."""
    cert, key = pki.self_signed("server", "DNS:weasyprint.example.com")
    exported = tmp_path / "exported.pem"
    exported.write_bytes("Bag Attributes\n    friendlyName: Zürich\n".encode() + cert.read_bytes())
    port = server(context=_server_context(exported, key))

    assert healthcheck_probe.main([str(port), str(exported)]) == 0


def test_expired_certificate_fails(server, pki: Pki, capsys: pytest.CaptureFixture[str]) -> None:
    """A client of the service would fail on it, so the container is unhealthy."""
    cert, key = pki.expired("server", "DNS:old.example.com")
    port = server(context=_server_context(cert, key))

    assert healthcheck_probe.main([str(port), str(cert)]) == 1
    assert "expired" in capsys.readouterr().err


def test_certificate_the_server_does_not_present_fails(server, pki: Pki, capsys: pytest.CaptureFixture[str]) -> None:
    presented, presented_key = pki.self_signed("presented", "DNS:weasyprint.example.com")
    configured, _ = pki.self_signed("configured", "DNS:weasyprint.example.com")
    port = server(context=_server_context(presented, presented_key))

    assert healthcheck_probe.main([str(port), str(configured)]) == 1
    assert "certificate verify failed" in capsys.readouterr().err


def test_certificate_without_a_name_fails(server, pki: Pki, capsys: pytest.CaptureFixture[str]) -> None:
    """A common name alone names no host for a hostname check, so no client could verify the server."""
    cert, key = pki.self_signed("localhost")
    port = server(context=_server_context(cert, key))

    assert healthcheck_probe.main([str(port), str(cert)]) == 1
    assert "names no host" in capsys.readouterr().err


def test_client_certificate_is_presented(server, pki: Pki) -> None:
    cert, key = pki.self_signed("server", "DNS:weasyprint.example.com")
    client_cert, client_key = pki.self_signed("probe", extended_key_usage="clientAuth")
    port = server(context=_server_context(cert, key, client_ca=client_cert))

    assert healthcheck_probe.main([str(port), str(cert), str(client_cert), str(client_key)]) == 0


def test_server_demanding_a_client_certificate_rejects_the_probe_without_one(server, pki: Pki) -> None:
    cert, key = pki.self_signed("server", "DNS:weasyprint.example.com")
    client_cert, _ = pki.self_signed("probe", extended_key_usage="clientAuth")
    port = server(context=_server_context(cert, key, client_ca=client_cert))

    assert healthcheck_probe.main([str(port), str(cert)]) == 1


def test_unreadable_client_certificate_fails(pki: Pki, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cert, _ = pki.self_signed("server", "DNS:weasyprint.example.com")
    missing = str(tmp_path / "missing.pem")

    assert healthcheck_probe.main(["1", str(cert), missing, missing]) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    "content",
    [
        None,
        "no certificate here\n",
        "-----BEGIN CERTIFICATE-----\nAAAA\n",
        "\xe4\n",
        "-----BEGIN CERTIFICATE-----\n\xe4\n-----END CERTIFICATE-----\n",  # no ASCII inside the block
    ],
)
def test_unusable_server_certificate_fails(tmp_path: Path, content: str | None, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing file, one without a PEM certificate, a broken one, one which is not text and a block which is not ASCII."""
    cert = tmp_path / "server.pem"
    if content is not None:
        cert.write_text(content, encoding="latin-1")

    assert healthcheck_probe.main(["1", str(cert)]) == 1
    assert capsys.readouterr().err.strip()


def test_file_without_a_certificate_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cert = tmp_path / "server.pem"
    cert.write_text("no certificate here\n", encoding="ascii")

    assert healthcheck_probe.main(["1", str(cert)]) == 1
    assert "holds no PEM certificate" in capsys.readouterr().err


# Arguments


@pytest.mark.parametrize("argv", [[], ["9080", "/tls/server.pem", "/tls/probe.pem"], ["1", "2", "3", "4", "5"]])
def test_wrong_number_of_arguments_is_reported(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert healthcheck_probe.main(argv) == 2
    assert "Usage" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["http://localhost:9080/health", "port", "0", "65536", "-1"])
def test_wrong_port_is_reported(port: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert healthcheck_probe.main([port]) == 2
    assert "Usage" in capsys.readouterr().err


def test_probe_runs_as_a_script(server, pki: Pki) -> None:
    """healthcheck.sh runs the file with python -I, outside of the package."""
    cert, key = pki.self_signed("server", "DNS:weasyprint.example.com")
    port = server(context=_server_context(cert, key))
    probe = Path(healthcheck_probe.__file__)

    completed = subprocess.run([sys.executable, "-I", str(probe), str(port), str(cert)], capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr


# Reading the names of a certificate


def test_server_name_prefers_the_first_dns_name(pki: Pki) -> None:
    cert, _ = pki.self_signed("server", "IP:10.1.2.3,DNS:first.example.com,DNS:second.example.com")

    assert healthcheck_probe.server_name(str(cert)) == "first.example.com"


def test_server_name_gives_a_wildcard_a_label(pki: Pki) -> None:
    cert, _ = pki.self_signed("server", "DNS:*.example.com")

    assert healthcheck_probe.server_name(str(cert)) == "healthcheck.example.com"


@pytest.mark.parametrize(("san", "expected"), [("IP:10.1.2.3", "10.1.2.3"), ("IP:2001:db8::1", "2001:db8::1")])
def test_server_name_falls_back_to_an_address(pki: Pki, san: str, expected: str) -> None:
    cert, _ = pki.self_signed("server", san)

    assert healthcheck_probe.server_name(str(cert)) == expected


def test_other_kinds_of_name_are_skipped(pki: Pki) -> None:
    cert, _ = pki.self_signed("server", "email:ops@example.com,URI:https://example.com,DNS:weasyprint.example.com")

    assert healthcheck_probe.subject_alt_names(healthcheck_probe.read_certificate(str(cert))) == [("DNS", "weasyprint.example.com")]


def test_certificate_without_extensions_has_no_names() -> None:
    # SEQUENCE { SEQUENCE { INTEGER 1 } }: a tbsCertificate with nothing but a serial number
    assert healthcheck_probe.subject_alt_names(bytes([0x30, 0x05, 0x30, 0x03, 0x02, 0x01, 0x01])) == []


def test_long_lengths_are_read() -> None:
    # A tbsCertificate whose content is 200 octets long, which takes the long form 0x81 0xC8
    tbs_certificate = bytes([0x30, 0x81, 0xC8, 0x04, 0x81, 0xC5]) + bytes(197)

    assert healthcheck_probe.subject_alt_names(bytes([0x30, 0x81, 0xCB]) + tbs_certificate) == []


@pytest.mark.parametrize(
    "der",
    [
        b"",  # nothing
        bytes([0x30]),  # a tag without a length
        bytes([0x30, 0x05, 0x30]),  # a length longer than what follows
        bytes([0x30, 0x80, 0x00, 0x00]),  # an indefinite length, which DER does not allow
        bytes([0x30, 0x85, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00]),  # a length of more than 4 octets
        bytes([0x30, 0x82, 0x01]),  # a long length cut short
        bytes([0x3F, 0x01, 0x00]),  # a high tag number
        bytes([0x02, 0x01, 0x01]),  # an INTEGER where the certificate starts
        bytes([0x30, 0x03, 0x02, 0x01, 0x01]),  # no tbsCertificate inside the certificate
    ],
)
def test_malformed_certificates_are_refused(der: bytes) -> None:
    with pytest.raises(ValueError, match="certificate"):
        healthcheck_probe.subject_alt_names(der)


def test_malformed_subject_alt_name_is_refused() -> None:
    # An extension with the subjectAltName id and a BOOLEAN where its OCTET STRING belongs
    extension = bytes([0x30, 0x08, 0x06, 0x03, 0x55, 0x1D, 0x11, 0x01, 0x01, 0xFF])
    extensions = bytes([0xA3, len(extension) + 2, 0x30, len(extension)]) + extension
    tbs_certificate = bytes([0x30, len(extensions)]) + extensions
    der = bytes([0x30, len(tbs_certificate)]) + tbs_certificate

    with pytest.raises(ValueError, match="subjectAltName"):
        healthcheck_probe.subject_alt_names(der)
