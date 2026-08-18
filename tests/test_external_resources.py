"""Tests for the policy applied to the external resources a document names."""

from __future__ import annotations

import base64
import contextlib
import http.client
import http.server
import ssl
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.external_resources import (
    ALLOWED_ORIGINS_VAR,
    MAX_SIZE_MB_VAR,
    POLICY_VAR,
    ExternalResourceError,
    Origin,
    PolicyUrlFetcher,
    ResourcePolicy,
    get_allowed_origins,
    get_max_size_bytes,
    get_policy,
    host_header,
    is_public_address,
    load_policy,
    proxy_authorization,
    tls_context,
)

POLICY_VARIABLES = (POLICY_VAR, ALLOWED_ORIGINS_VAR, MAX_SIZE_MB_VAR, "EXTERNAL_RESOURCES_TIMEOUT_SECONDS")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

# A body announced far larger than it arrives, a byte every 50 ms.
DRIP_BYTES = 200

# How long a server which announces a body and then sends nothing holds it.
STALL_SECONDS = 3

REDIRECT_TARGETS = {
    "/redirect-to-image": "/image.png",
    "/redirect-to-internal": "http://169.254.169.254/latest/meta-data/",
    "/redirect-loop": "/redirect-loop",
    "/redirect-to-ftp": "ftp://example.org/font.ttf",
    "/nested/redirect-relative": "../image.png",
    "/redirect-query-only": "?ignored=1",
}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an unconfigured environment."""
    for name in POLICY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves the responses the tests need, on the loopback interface."""

    def do_GET(self) -> None:
        routes = {
            "/image.png": (200, "image/png", PNG),
            "/page.html": (200, "text/html", b"<html></html>"),
            "/secret.txt": (200, "text/plain", b"top secret"),
            "/undeclared": (200, "application/octet-stream", PNG),
            "/undeclared-text": (200, "application/octet-stream", b"top secret"),
            "/huge.png": (200, "image/png", PNG + b"\x00" * (2 * 1024 * 1024)),
            "/missing": (404, "text/plain", b"gone"),
        }
        path, _, query = self.path.partition("?")
        if path == "/dripping.png":
            self._drip()
            return
        if path == "/redirect-dripping":
            self._drip(status=302, location="/image.png")
            return
        if path == "/stalling.png":
            self._stall()
            return
        if path == "/redirect-query-only" and query:
            path = "/image.png"
        elif path in REDIRECT_TARGETS:
            self._redirect(path)
            return
        status, content_type, body = routes.get(path, (404, "text/plain", b"gone"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drip(self, status: int = 200, location: str | None = None) -> None:
        """Answer a byte at a time, the shape which outlasts a timer each byte resets."""
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(DRIP_BYTES))
        self.end_headers()
        with contextlib.suppress(OSError):
            for _ in range(DRIP_BYTES):
                self.wfile.write(b"\x00")
                self.wfile.flush()
                time.sleep(0.05)

    def _stall(self) -> None:
        """Announce a body and never send it, the shape which blocks a single read."""
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(DRIP_BYTES))
        self.end_headers()
        with contextlib.suppress(OSError):
            time.sleep(STALL_SECONDS)

    def _redirect(self, path: str) -> None:
        """Answer the redirects the tests follow."""
        self.send_response(302)
        self.send_header("Location", REDIRECT_TARGETS[path])
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        """Keep the test output clean."""


@pytest.fixture
def local_server() -> Iterator[str]:
    """A server on the loopback interface, which the policy treats as internal."""
    # Threading: a handler which answers slowly must not hold the others.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_the_closed_policy_is_the_default() -> None:
    assert get_policy() is ResourcePolicy.BLOCK_INTERNAL


def test_an_unknown_policy_falls_back_to_the_closed_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(POLICY_VAR, "ALLOW_EVERYTHING")

    assert get_policy() is ResourcePolicy.BLOCK_INTERNAL


@pytest.mark.parametrize("configured", ["allowlist_only", "ALLOWLIST_ONLY", " AllowList_Only "])
def test_the_policy_is_read_regardless_of_case(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    monkeypatch.setenv(POLICY_VAR, configured)

    assert get_policy() is ResourcePolicy.ALLOWLIST_ONLY


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.1.1", False),
        ("172.16.0.1", False),
        ("169.254.169.254", False),  # the cloud metadata address
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1", False),
        ("fd00::1", False),
        ("::ffff:127.0.0.1", False),  # loopback wearing an IPv6 mapping
        ("2001:4860:4860::8888", True),
        ("224.0.0.1", False),  # multicast
    ],
)
def test_which_addresses_are_public(address: str, public: bool) -> None:
    assert is_public_address(address) is public


@pytest.mark.parametrize(
    ("entry", "scheme", "host", "port", "matches"),
    [
        ("cdn.intranet", "http", "cdn.intranet", 80, True),
        ("cdn.intranet", "https", "cdn.intranet", 8443, True),
        ("cdn.intranet", "https", "other.intranet", 443, False),
        ("cdn.intranet:8443", "https", "cdn.intranet", 8443, True),
        ("cdn.intranet:8443", "https", "cdn.intranet", 443, False),
        ("https://cdn.intranet", "https", "cdn.intranet", 443, True),
        ("https://cdn.intranet", "http", "cdn.intranet", 80, False),
        ("https://cdn.intranet:8443", "https", "cdn.intranet", 8443, True),
        ("CDN.Intranet", "https", "cdn.intranet", 443, True),
    ],
)
def test_origin_entries(entry: str, scheme: str, host: str, port: int, matches: bool) -> None:
    assert Origin.parse(entry).matches(scheme, host, port) is matches


@pytest.mark.parametrize("entry", ["http://", "host name", "ftp://cdn.intranet", "cdn.intranet:port"])
def test_an_unusable_origin_entry_is_reported(entry: str) -> None:
    with pytest.raises(ExternalResourceError, match=ALLOWED_ORIGINS_VAR):
        Origin.parse(entry)


def test_origins_are_read_as_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOWED_ORIGINS_VAR, "cdn.intranet, https://images.intranet:8443 , ")

    assert get_allowed_origins() == (Origin(host="cdn.intranet"), Origin(host="images.intranet", scheme="https", port=8443))


@pytest.mark.parametrize(("configured", "expected_mb"), [("", 16), ("32", 32), ("zero", 16), ("0", 16), ("-1", 16)])
def test_the_size_limit_is_read(monkeypatch: pytest.MonkeyPatch, configured: str, expected_mb: int) -> None:
    if configured:
        monkeypatch.setenv(MAX_SIZE_MB_VAR, configured)

    assert get_max_size_bytes() == expected_mb * 1024 * 1024


@pytest.mark.parametrize("url", ["ftp://example.org/font.ttf", "gopher://example.org/x", "jar:file:///etc/passwd!/x"])
def test_other_schemes_are_refused(url: str) -> None:
    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="scheme"):
        fetcher.fetch(url)


def test_a_data_url_passes() -> None:
    response = PolicyUrlFetcher().fetch("data:image/png;base64,iVBORw0KGgo=")

    assert response.content_type == "image/png"


def test_a_file_is_refused_without_an_upload_directory(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    fetcher = PolicyUrlFetcher()
    url = secret.as_uri()

    with pytest.raises(ExternalResourceError, match="file of this container"):
        fetcher.fetch(url)


def test_a_file_outside_the_upload_directory_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    fetcher = PolicyUrlFetcher(allowed_file_root=uploads)
    url = secret.as_uri()

    with pytest.raises(ExternalResourceError, match="uploaded with it"):
        fetcher.fetch(url)


def test_a_file_of_the_upload_directory_is_loaded(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    attachment = uploads / "attachment.bin"
    attachment.write_bytes(b"an uploaded file")

    response = PolicyUrlFetcher(allowed_file_root=uploads).fetch(attachment.as_uri())

    assert response.read() == b"an uploaded file"


def test_a_traversal_out_of_the_upload_directory_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    fetcher = PolicyUrlFetcher(allowed_file_root=uploads)
    url = f"{uploads.as_uri()}/../secret.txt"

    with pytest.raises(ExternalResourceError, match="uploaded with it"):
        fetcher.fetch(url)


def test_an_internal_address_is_refused(local_server: str) -> None:
    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="not an address on the internet"):
        fetcher.fetch(f"{local_server}/image.png")


def test_an_internal_address_is_loaded_when_its_origin_is_allowed(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    port = local_server.rsplit(":", 1)[1]
    monkeypatch.setenv(ALLOWED_ORIGINS_VAR, f"127.0.0.1:{port}")

    response = PolicyUrlFetcher().fetch(f"{local_server}/image.png")

    assert response.status == 200
    assert response.content_type == "image/png"


def test_the_open_policy_loads_an_internal_address(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    assert PolicyUrlFetcher().fetch(f"{local_server}/image.png").status == 200


def test_the_allowlist_policy_refuses_an_address_which_is_not_listed(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOWLIST_ONLY.value)

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match=ALLOWED_ORIGINS_VAR):
        fetcher.fetch(f"{local_server}/image.png")


def test_a_body_which_is_not_a_resource_is_refused(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """This is the exfiltration case: a document asking for a body to be read back."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="not an image, a font or a stylesheet"):
        fetcher.fetch(f"{local_server}/secret.txt")


def test_an_undeclared_body_is_sniffed(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    assert PolicyUrlFetcher().fetch(f"{local_server}/undeclared").status == 200

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="not an image or a font"):
        fetcher.fetch(f"{local_server}/undeclared-text")


def test_a_body_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv(MAX_SIZE_MB_VAR, "1")

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="larger than"):
        fetcher.fetch(f"{local_server}/huge.png")


def test_an_error_status_is_reported(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="answered 404"):
        fetcher.fetch(f"{local_server}/missing")


def test_a_proxied_host_has_to_be_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy resolves the name itself, so such a request cannot be bound to a checked address."""
    monkeypatch.setenv("http_proxy", "http://proxy.intranet:3128")

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="through a proxy"):
        fetcher.fetch("http://example.org/image.png")


def test_a_redirect_is_followed(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    response = PolicyUrlFetcher().fetch(f"{local_server}/redirect-to-image")

    assert response.content_type == "image/png"


def test_a_redirect_into_the_internal_network_is_refused(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A hop is vetted like the address it came from, or a redirect would be the way around the policy."""
    port = local_server.rsplit(":", 1)[1]
    monkeypatch.setenv(ALLOWED_ORIGINS_VAR, f"127.0.0.1:{port}")

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="not an address on the internet"):
        fetcher.fetch(f"{local_server}/redirect-to-internal")


def test_a_redirect_loop_ends(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="redirects more than"):
        fetcher.fetch(f"{local_server}/redirect-loop")


def test_a_redirect_to_another_scheme_is_refused(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A hop names its own scheme, and it is gated like the address the document named."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="scheme"):
        fetcher.fetch(f"{local_server}/redirect-to-ftp")


def test_a_relative_redirect_is_resolved_by_the_standard_rules(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    response = PolicyUrlFetcher().fetch(f"{local_server}/nested/redirect-relative")

    assert response.content_type == "image/png"


def test_a_query_only_redirect_stays_on_the_same_path(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """Such a Location keeps the path, which a hand written resolver gets wrong."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    response = PolicyUrlFetcher().fetch(f"{local_server}/redirect-query-only")

    assert response.content_type == "image/png"


def test_a_percent_encoded_traversal_is_refused(tmp_path: Path) -> None:
    """The check reads the path the loader reads, decoded."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    fetcher = PolicyUrlFetcher(allowed_file_root=uploads)
    url = f"{uploads.as_uri()}/%2e%2e/secret.txt"

    with pytest.raises(ExternalResourceError, match="uploaded with it"):
        fetcher.fetch(url)


def test_the_tls_context_refuses_the_old_protocol_versions() -> None:
    context = tls_context()

    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.parametrize(
    ("host", "port", "scheme", "expected"),
    [
        ("cdn.intranet", 80, "http", "cdn.intranet"),
        ("cdn.intranet", 8080, "http", "cdn.intranet:8080"),
        ("cdn.intranet", 443, "https", "cdn.intranet"),
        ("::1", 80, "http", "[::1]"),
        ("2001:db8::1", 8443, "https", "[2001:db8::1]:8443"),
    ],
)
def test_the_host_header_carries_the_name(host: str, port: int, scheme: str, expected: str) -> None:
    """An IPv6 literal needs its brackets, or the header names something else."""
    assert host_header(host, port, scheme) == expected


def test_a_plain_connection_is_bound_to_the_vetted_address() -> None:
    """The pinning itself: the socket goes to the address, the name only travels in the header."""
    connection = PolicyUrlFetcher()._direct("http", "cdn.intranet", 80, "93.184.216.34")

    assert connection.host == "93.184.216.34"
    assert connection.port == 80


def test_an_https_resource_through_a_proxy_is_tunnelled_with_tls() -> None:
    """A plain connection with a tunnel would put the request into it in the clear."""
    connection = PolicyUrlFetcher()._through_proxy("http://proxy.intranet:3128", "https", "cdn.example", 443)

    assert isinstance(connection, http.client.HTTPSConnection)
    assert connection.host == "proxy.intranet"
    assert connection.port == 3128
    assert connection._tunnel_host == "cdn.example"


def test_a_plain_resource_through_a_proxy_needs_no_tunnel() -> None:
    connection = PolicyUrlFetcher()._through_proxy("http://proxy.intranet:3128", "http", "cdn.example", 80)

    assert not isinstance(connection, http.client.HTTPSConnection)
    assert connection._tunnel_host is None


@pytest.mark.filterwarnings("error::ResourceWarning")
def test_the_next_vetted_address_is_tried(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A dual stack host answers with an address this container may have no route to."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv("EXTERNAL_RESOURCES_TIMEOUT_SECONDS", "0.3")
    port = int(local_server.rsplit(":", 1)[1])
    # 192.0.2.1 is the documentation range: reserved, and no route leads there.
    monkeypatch.setattr("app.external_resources.resolve", lambda host, port_number: ("192.0.2.1", "127.0.0.1"))

    response = PolicyUrlFetcher().fetch(f"http://127.0.0.1:{port}/image.png")

    assert response.content_type == "image/png"


def test_the_timeout_bounds_the_whole_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise the ceiling would be hops times addresses times the configured seconds."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv("EXTERNAL_RESOURCES_TIMEOUT_SECONDS", "0.4")
    # Addresses of the documentation range: reserved, and no route leads there.
    monkeypatch.setattr("app.external_resources.resolve", lambda host, port: ("192.0.2.1", "192.0.2.2", "192.0.2.3"))
    fetcher = PolicyUrlFetcher()

    started = time.monotonic()
    with pytest.raises(ExternalResourceError):
        fetcher.fetch("http://cdn.example/image.png")
    elapsed = time.monotonic() - started

    assert elapsed < 2, f"the fetch spent {elapsed:.1f}s, the limit is 0.4s per resource"


def test_a_request_is_never_made_to_a_name() -> None:
    """Without an address there is nothing which was vetted, so there is nothing to ask."""
    fetcher = PolicyUrlFetcher()

    with pytest.raises(ExternalResourceError, match="no address which may be connected to"):
        fetcher._send("http", "cdn.example", 80, (), "http://cdn.example/image.png")


def test_a_body_which_arrives_too_slowly_is_given_up(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A server dripping a byte holds the connection past the deadline of the load otherwise."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv("EXTERNAL_RESOURCES_TIMEOUT_SECONDS", "0.5")
    fetcher = PolicyUrlFetcher()

    started = time.monotonic()
    with pytest.raises(ExternalResourceError, match="took longer than"):
        fetcher.fetch(f"{local_server}/dripping.png")
    elapsed = time.monotonic() - started

    assert elapsed < 3, f"the fetch spent {elapsed:.1f}s on a body it should have given up on"


def test_a_redirect_body_which_arrives_too_slowly_is_given_up(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A hop is read under the deadline of the load, or a dripping redirect holds it open."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv("EXTERNAL_RESOURCES_TIMEOUT_SECONDS", "0.5")
    fetcher = PolicyUrlFetcher()

    started = time.monotonic()
    with pytest.raises(ExternalResourceError, match="took longer than"):
        fetcher.fetch(f"{local_server}/redirect-dripping")
    elapsed = time.monotonic() - started

    assert elapsed < 3, f"the fetch spent {elapsed:.1f}s on a hop it should have given up on"


def test_a_name_is_not_looked_up_once_the_deadline_has_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lookup is bounded by the resolver, so a chain of hops may not start another."""
    fetcher = PolicyUrlFetcher()

    def unreachable(host: str, port: int) -> tuple[str, ...]:
        raise AssertionError("the name was looked up after the load ran out of time")

    monkeypatch.setattr("app.external_resources.resolve", unreachable)
    passed = time.monotonic() - 1

    with pytest.raises(ExternalResourceError, match="took longer than"):
        fetcher._vet("http://cdn.example/image.png", passed)


def test_a_body_which_never_arrives_is_refused_like_every_other_failure(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A peer which announces a body and sends nothing spends the budget in one read."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv("EXTERNAL_RESOURCES_TIMEOUT_SECONDS", "0.5")
    fetcher = PolicyUrlFetcher()

    started = time.monotonic()
    with pytest.raises(ExternalResourceError, match="took longer than"):
        fetcher.fetch(f"{local_server}/stalling.png")
    elapsed = time.monotonic() - started

    assert elapsed < STALL_SECONDS, f"the fetch spent {elapsed:.1f}s waiting for a body which never came"


def _fetch_recording_the_connection(fetcher: PolicyUrlFetcher, monkeypatch: pytest.MonkeyPatch, url: str) -> list[http.client.HTTPConnection]:
    """Fetch a url and hand back every connection the fetcher opened for it."""
    connections: list[http.client.HTTPConnection] = []
    send = PolicyUrlFetcher._send

    def recording(self: PolicyUrlFetcher, *args: Any, **kwargs: Any) -> Any:
        connection, response = send(self, *args, **kwargs)
        connections.append(connection)
        return connection, response

    monkeypatch.setattr(PolicyUrlFetcher, "_send", recording)
    with contextlib.suppress(ExternalResourceError):
        fetcher.fetch(url)
    return connections


def test_the_connection_of_a_hop_is_closed(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """Closing the response releases its reader, not the socket the hop opened."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)

    connections = _fetch_recording_the_connection(PolicyUrlFetcher(), monkeypatch, f"{local_server}/redirect-to-image")

    assert len(connections) == 2, "a hop and the resource it points at are two connections"
    assert all(connection.sock is None for connection in connections)


def test_the_connection_is_closed_when_the_resource_is_refused(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    """A refusal releases the socket where it is raised, not when the traceback is dropped."""
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOW_ALL.value)
    monkeypatch.setenv(MAX_SIZE_MB_VAR, "1")

    connections = _fetch_recording_the_connection(PolicyUrlFetcher(), monkeypatch, f"{local_server}/huge.png")

    assert connections, "the fetcher opened no connection"
    assert all(connection.sock is None for connection in connections)


def test_a_proxy_which_asks_for_credentials_is_given_them() -> None:
    """urllib sent them before this fetcher existed, so a deployment behind such a proxy keeps working."""
    header = proxy_authorization("http://user:p%40ss@proxy.intranet:3128")

    assert header == {"Proxy-Authorization": "Basic " + base64.b64encode(b"user:p@ss").decode()}


def test_a_proxy_without_credentials_is_given_none() -> None:
    assert proxy_authorization("http://proxy.intranet:3128") == {}


def test_an_https_proxy_without_a_port_is_reached_on_the_port_of_its_scheme() -> None:
    """'https_proxy=https://proxy.intranet' is 443, which the http default hid."""
    connection = PolicyUrlFetcher()._through_proxy("https://proxy.intranet", "http", "cdn.example", 80)

    assert connection.port == 443


def test_a_tunnel_carries_the_credentials_of_the_proxy() -> None:
    """The request travels inside the tunnel, so the CONNECT is where they belong."""
    connection = PolicyUrlFetcher()._through_proxy("http://user:pass@proxy.intranet:3128", "https", "cdn.example", 443)

    assert connection._tunnel_headers["Proxy-Authorization"] == "Basic " + base64.b64encode(b"user:pass").decode()


def test_a_malformed_origin_stops_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo which fails at request time is an outage found by traffic instead of by the start."""
    monkeypatch.setenv(ALLOWED_ORIGINS_VAR, "cdn.intranet:por")

    with pytest.raises(ExternalResourceError, match="not a valid entry"):
        load_policy()


def test_a_readable_configuration_is_reported_at_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(POLICY_VAR, ResourcePolicy.ALLOWLIST_ONLY.value)
    monkeypatch.setenv(ALLOWED_ORIGINS_VAR, "cdn.intranet, https://fonts.example")

    assert load_policy() is ResourcePolicy.ALLOWLIST_ONLY
