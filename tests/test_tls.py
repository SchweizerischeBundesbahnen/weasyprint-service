"""Tests for the optional TLS configuration."""

import asyncio
import shutil
import ssl
import subprocess
from pathlib import Path

import pytest

from app import metrics_server, weasyprint_service_application
from app.tls import (
    API_TLS_PREFIX,
    METRICS_TLS_PREFIX,
    TlsConfigurationError,
    get_scheme,
    get_tls_options,
    load_tls_options,
    verify_tls_material,
)

TLS_VARIABLES = [prefix + suffix for prefix in (API_TLS_PREFIX, METRICS_TLS_PREFIX) for suffix in ("CERT_FILE", "KEY_FILE", "KEY_PASSWORD", "CLIENT_CA_FILE", "CLIENT_AUTH")]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an unconfigured environment."""
    for name in TLS_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def pem_files(tmp_path: Path) -> tuple[str, str, str]:
    """Three readable files standing in for a certificate, a key and a CA."""
    paths = []
    for name in ("cert.pem", "key.pem", "ca.pem"):
        path = tmp_path / name
        path.write_text(f"-----BEGIN {name}-----\n", encoding="utf-8")
        paths.append(str(path))
    return paths[0], paths[1], paths[2]


def test_unconfigured_environment_serves_plain_http() -> None:
    assert get_tls_options() == {}
    assert get_scheme({}) == "http"


def test_whitespace_only_value_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TLS_CERT_FILE", "   ")
    monkeypatch.setenv("TLS_KEY_FILE", "   ")

    assert get_tls_options() == {}


def test_certificate_and_key_enable_tls(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)

    options = get_tls_options()

    assert options == {"ssl_certfile": cert, "ssl_keyfile": key}
    assert get_scheme(options) == "https"


def test_key_password_is_passed_unchanged(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)
    monkeypatch.setenv("TLS_KEY_PASSWORD", "  pass phrase  ")

    assert get_tls_options()["ssl_keyfile_password"] == "  pass phrase  "


@pytest.mark.parametrize(("mode", "expected"), [("optional", ssl.CERT_OPTIONAL), ("required", ssl.CERT_REQUIRED), ("REQUIRED", ssl.CERT_REQUIRED)])
def test_client_authentication_modes(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str], mode: str, expected: int) -> None:
    cert, key, ca = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)
    monkeypatch.setenv("TLS_CLIENT_AUTH", mode)
    monkeypatch.setenv("TLS_CLIENT_CA_FILE", ca)

    options = get_tls_options()

    assert options["ssl_ca_certs"] == ca
    assert options["ssl_cert_reqs"] == expected


def test_metrics_server_is_configured_on_its_own(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    """The API prefix must not leak into the metrics server, nor the other way round."""
    cert, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)

    assert get_tls_options(API_TLS_PREFIX) != {}
    assert get_tls_options(METRICS_TLS_PREFIX) == {}


def test_metrics_prefix_enables_tls_alone(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, _ = pem_files
    monkeypatch.setenv("METRICS_TLS_CERT_FILE", cert)
    monkeypatch.setenv("METRICS_TLS_KEY_FILE", key)

    assert get_tls_options(METRICS_TLS_PREFIX) == {"ssl_certfile": cert, "ssl_keyfile": key}
    assert get_tls_options(API_TLS_PREFIX) == {}


def test_certificate_without_key_is_rejected(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, _, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)

    with pytest.raises(TlsConfigurationError, match="TLS_KEY_FILE is missing"):
        get_tls_options()


def test_key_without_certificate_is_rejected(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    _, key, _ = pem_files
    monkeypatch.setenv("TLS_KEY_FILE", key)

    with pytest.raises(TlsConfigurationError, match="TLS_CERT_FILE is missing"):
        get_tls_options()


def test_unreadable_certificate_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pem_files: tuple[str, str, str]) -> None:
    _, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", str(tmp_path / "absent.pem"))
    monkeypatch.setenv("TLS_KEY_FILE", key)

    with pytest.raises(TlsConfigurationError, match="which is not a file"):
        get_tls_options()


def test_unknown_client_auth_mode_is_rejected(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, ca = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)
    monkeypatch.setenv("TLS_CLIENT_AUTH", "yes-please")
    monkeypatch.setenv("TLS_CLIENT_CA_FILE", ca)

    with pytest.raises(TlsConfigurationError, match="expected one of"):
        get_tls_options()


def test_client_auth_without_ca_is_rejected(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)
    monkeypatch.setenv("TLS_CLIENT_AUTH", "required")

    with pytest.raises(TlsConfigurationError, match="TLS_CLIENT_CA_FILE is required"):
        get_tls_options()


def test_client_ca_without_client_auth_is_rejected(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    """A CA which nothing verifies against is a configuration mistake, not a default."""
    cert, key, ca = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)
    monkeypatch.setenv("TLS_CLIENT_CA_FILE", ca)

    with pytest.raises(TlsConfigurationError, match="no client certificate would ever be verified"):
        get_tls_options()


def test_client_rules_without_a_certificate_are_rejected(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    """Client authentication configured while TLS is off would silently do nothing."""
    _, _, ca = pem_files
    monkeypatch.setenv("TLS_CLIENT_AUTH", "required")
    monkeypatch.setenv("TLS_CLIENT_CA_FILE", ca)

    with pytest.raises(TlsConfigurationError, match="without TLS_CERT_FILE"):
        get_tls_options()


def test_material_which_does_not_load_is_reported(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    """A readable file is not usable material: the key has to match its certificate."""
    cert, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)

    with pytest.raises(TlsConfigurationError, match="do not load together"):
        load_tls_options()


def test_nothing_is_loaded_without_a_configuration() -> None:
    assert load_tls_options() == {}
    verify_tls_material({})


def test_real_material_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is not available to produce a certificate")

    cert = tmp_path / "server.pem"
    key = tmp_path / "server.key"
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("TLS_CERT_FILE", str(cert))
    monkeypatch.setenv("TLS_KEY_FILE", str(key))

    assert load_tls_options() == {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}


def test_api_server_is_started_with_the_configured_options(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, _ = pem_files
    monkeypatch.setenv("TLS_CERT_FILE", cert)
    monkeypatch.setenv("TLS_KEY_FILE", key)
    monkeypatch.setattr(weasyprint_service_application, "load_tls_options", lambda: {"ssl_certfile": cert, "ssl_keyfile": key})
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(weasyprint_service_application.uvicorn, "run", fake_run)
    weasyprint_service_application.start_server(9080)

    assert captured["ssl_certfile"] == cert
    assert captured["ssl_keyfile"] == key


def test_metrics_server_is_configured_with_its_own_options(monkeypatch: pytest.MonkeyPatch, pem_files: tuple[str, str, str]) -> None:
    cert, key, _ = pem_files
    monkeypatch.setenv("METRICS_TLS_CERT_FILE", cert)
    monkeypatch.setenv("METRICS_TLS_KEY_FILE", key)
    monkeypatch.setattr(metrics_server, "load_tls_options", lambda prefix: {"ssl_certfile": cert, "ssl_keyfile": key})
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeServer:
        started = True

        def __init__(self, config: FakeConfig) -> None:
            self.config = config

        async def serve(self) -> None:
            return None

    monkeypatch.setattr(metrics_server.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(metrics_server.uvicorn, "Server", FakeServer)

    asyncio.run(metrics_server.MetricsServer(port=9180).start())

    assert captured["ssl_certfile"] == cert
    assert captured["ssl_keyfile"] == key
