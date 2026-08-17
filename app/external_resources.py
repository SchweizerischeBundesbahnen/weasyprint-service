"""Policy for the external resources a document names.

A document reaching this service can name an absolute address for an image, a
font or a stylesheet, and WeasyPrint loads it. Left alone, that turns the
service into a fetcher for whatever its network reaches, and ``<link
rel="attachment">`` returns the answer inside the produced PDF.

Every load therefore goes through :class:`PolicyUrlFetcher`:

- ``data:`` is local and passes untouched.
- ``file:`` is refused, except under the temporary directory of the request,
  where the attachments endpoint puts the files it received itself.
- ``http`` and ``https`` are vetted address by address, and the request is bound
  to what was vetted, so a second name lookup cannot answer differently. Every
  redirect hop is vetted again. The body is capped, and its kind has to be an
  image, a font or a stylesheet.
- Every other scheme, ``ftp:`` among them, is refused.

Three variables configure it: ``EXTERNAL_RESOURCES_POLICY``,
``EXTERNAL_RESOURCES_ALLOWED_ORIGINS`` and ``EXTERNAL_RESOURCES_MAX_SIZE_MB``.
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import os
import re
import socket
import ssl
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import getproxies, proxy_bypass, url2pathname

from weasyprint.urls import URLFetcher, URLFetcherResponse  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

POLICY_VAR = "EXTERNAL_RESOURCES_POLICY"
ALLOWED_ORIGINS_VAR = "EXTERNAL_RESOURCES_ALLOWED_ORIGINS"
MAX_SIZE_MB_VAR = "EXTERNAL_RESOURCES_MAX_SIZE_MB"
TIMEOUT_VAR = "EXTERNAL_RESOURCES_TIMEOUT_SECONDS"

DEFAULT_MAX_SIZE_MB = 16
DEFAULT_TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 5
HTTP_OK = 200
HTTP_REDIRECT_RANGE = range(300, 400)
DEFAULT_PORTS = {"http": 80, "https": 443}

# What a document may load: an image, a font or a stylesheet. Anything else is
# not a resource of a page, it is a body someone wants read back.
ALLOWED_CONTENT_TYPES = ("image/", "font/", "application/font", "application/x-font", "application/vnd.ms-fontobject", "text/css")
UNDECLARED_CONTENT_TYPES = ("application/octet-stream", "binary/octet-stream", "")

# Signatures of the kinds above, for a server which declares nothing useful.
CONTENT_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",
    b"GIF89a",
    b"BM",  # BMP
    b"\x00\x00\x01\x00",  # ICO
    b"II*\x00",  # TIFF little endian
    b"MM\x00*",  # TIFF big endian
    b"wOFF",
    b"wOF2",
    b"\x00\x01\x00\x00",  # TrueType
    b"OTTO",  # OpenType
    b"ttcf",  # TrueType collection
)
RIFF_SIGNATURE = b"RIFF"
WEBP_SIGNATURE = b"WEBP"

ORIGIN_PATTERN = re.compile(r"^(?:(?P<scheme>https?)://)?(?P<host>\[[^\]]+\]|[^:/\s]+)(?::(?P<port>\d+))?$", re.IGNORECASE)


class ExternalResourceError(ValueError):
    """Raised when a resource may not be loaded, with the reason."""


class ResourcePolicy(StrEnum):
    """Where a document may load a resource from."""

    BLOCK_INTERNAL = "BLOCK_INTERNAL"
    ALLOWLIST_ONLY = "ALLOWLIST_ONLY"
    ALLOW_ALL = "ALLOW_ALL"


@dataclass(frozen=True)
class Origin:
    """An entry of the allowed origins, written ``[scheme://]host[:port]``.

    What an entry leaves out is not compared: ``cdn.intranet`` allows that host
    under either scheme on any port.
    """

    host: str
    scheme: str | None = None
    port: int | None = None

    @classmethod
    def parse(cls, value: str) -> Origin:
        match = ORIGIN_PATTERN.match(value.strip())
        if not match:
            raise ExternalResourceError(f"'{value}' is not a valid entry of {ALLOWED_ORIGINS_VAR}, expected [scheme://]host[:port]")
        scheme = match["scheme"].lower() if match["scheme"] else None
        if match["port"]:
            port = int(match["port"])
        elif scheme:
            port = DEFAULT_PORTS[scheme]
        else:
            port = None
        return cls(host=match["host"].strip("[]").lower(), scheme=scheme, port=port)

    def matches(self, scheme: str, host: str, port: int) -> bool:
        if self.host != host.strip("[]").lower():
            return False
        if self.scheme and self.scheme != scheme:
            return False
        return not (self.port and self.port != port)


def _read(name: str) -> str:
    return os.environ.get(name, "").strip()


def get_policy() -> ResourcePolicy:
    """Read the configured policy, falling back to the closed one."""
    configured = _read(POLICY_VAR).upper()
    if not configured:
        return ResourcePolicy.BLOCK_INTERNAL
    try:
        return ResourcePolicy(configured)
    except ValueError:
        allowed = ", ".join(policy.value for policy in ResourcePolicy)
        logger.warning("%s is '%s', expected one of: %s. Falling back to %s", POLICY_VAR, configured, allowed, ResourcePolicy.BLOCK_INTERNAL.value)
        return ResourcePolicy.BLOCK_INTERNAL


def get_allowed_origins() -> tuple[Origin, ...]:
    """Read the origins which are allowed whatever they resolve to."""
    raw = _read(ALLOWED_ORIGINS_VAR)
    return tuple(Origin.parse(entry) for entry in raw.split(",") if entry.strip())


def get_max_size_bytes() -> int:
    """Read the size a single resource may reach."""
    configured = _read(MAX_SIZE_MB_VAR)
    if not configured:
        return DEFAULT_MAX_SIZE_MB * 1024 * 1024
    try:
        megabytes = int(configured)
    except ValueError:
        logger.warning("%s is '%s', which is not a number. Falling back to %d", MAX_SIZE_MB_VAR, configured, DEFAULT_MAX_SIZE_MB)
        return DEFAULT_MAX_SIZE_MB * 1024 * 1024
    if megabytes <= 0:
        logger.warning("%s is '%s', which is not positive. Falling back to %d", MAX_SIZE_MB_VAR, configured, DEFAULT_MAX_SIZE_MB)
        return DEFAULT_MAX_SIZE_MB * 1024 * 1024
    return megabytes * 1024 * 1024


def get_timeout_seconds() -> float:
    """Read the time a single request may take."""
    configured = _read(TIMEOUT_VAR)
    try:
        timeout = float(configured) if configured else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        logger.warning("%s is '%s', which is not a number. Falling back to %d", TIMEOUT_VAR, configured, DEFAULT_TIMEOUT_SECONDS)
        return DEFAULT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS


def is_public_address(address: str) -> bool:
    """Whether an address names a host on the internet.

    Loopback, private ranges, link local (the cloud metadata address among them),
    the unspecified address and everything reserved are not.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped
    return parsed.is_global and not parsed.is_multicast


def tls_context() -> ssl.SSLContext:
    """The context a request is made with: certificates verified, TLS 1.2 at least."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def host_header(host: str, port: int, scheme: str) -> str:
    """The Host header of a request, with an IPv6 literal in the brackets it needs."""
    literal = f"[{host}]" if ":" in host else host
    return literal if port == DEFAULT_PORTS[scheme] else f"{literal}:{port}"


def resolve(host: str, port: int) -> tuple[str, ...]:
    """Resolve a host to every address it answers with."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise ExternalResourceError(f"'{host}' does not resolve: {e}") from e
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


class PolicyUrlFetcher(URLFetcher):
    """The fetcher WeasyPrint loads every external resource with."""

    def __init__(self, allowed_file_root: Path | None = None) -> None:
        """
        Args:
            allowed_file_root: Directory whose files may be loaded through
                ``file:``, which is the temporary directory of a request with
                attachments. Nothing outside it is readable.
        """
        super().__init__(allow_redirects=False)
        self.allowed_file_root = allowed_file_root.resolve() if allowed_file_root else None
        self.policy = get_policy()
        self.allowed_origins = get_allowed_origins()
        self.max_size_bytes = get_max_size_bytes()
        self.timeout_seconds = get_timeout_seconds()

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> Any:
        """Load a resource, or explain why it may not be loaded."""
        scheme = urlsplit(url).scheme.lower()

        if scheme == "data":
            return super().fetch(url, headers)
        if scheme == "file":
            self._check_file(url)
            return super().fetch(url, headers)
        if scheme in DEFAULT_PORTS:
            return self._fetch_remote(url, headers)

        raise ExternalResourceError(f"'{scheme}:' is not a scheme a document may load from")

    def _check_file(self, url: str) -> None:
        """A file is readable only under the temporary directory of the request."""
        if self.allowed_file_root is None:
            raise ExternalResourceError("a document may not load a file of this container")
        # Decoded first: the check has to read the path the loader reads, or
        # '%2e%2e' walks out of the directory as an ordinary looking component.
        path = Path(url2pathname(urlsplit(url).path)).resolve()
        if not path.is_relative_to(self.allowed_file_root):
            raise ExternalResourceError("a document may only load the files uploaded with it")

    def _check_origin(self, scheme: str, host: str, port: int) -> bool:
        """Whether the origin is one the configuration allows whatever it resolves to."""
        return any(origin.matches(scheme, host, port) for origin in self.allowed_origins)

    def _check_addresses(self, addresses: Iterable[str], host: str) -> None:
        """Every address a host answers with has to be public."""
        for address in addresses:
            if not is_public_address(address):
                raise ExternalResourceError(f"'{host}' resolves to {address}, which is not an address on the internet")

    def _vet(self, url: str) -> tuple[str, str, int, str | None]:
        """Vet an address and return what a request to it needs.

        Returns:
            The scheme, host, port, and the address to connect to, which is
            ``None`` when a proxy carries the request and resolves the name.
        """
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PORTS:
            raise ExternalResourceError(f"'{scheme}:' is not a scheme a document may load from")
        host = parts.hostname or ""
        port = parts.port or DEFAULT_PORTS[scheme]
        if not host:
            raise ExternalResourceError(f"'{url}' names no host")

        allowlisted = self._check_origin(scheme, host, port)
        if self.policy is ResourcePolicy.ALLOWLIST_ONLY and not allowlisted:
            raise ExternalResourceError(f"'{host}' is not listed in {ALLOWED_ORIGINS_VAR}")

        if self._proxy_for(scheme, host):
            # A proxy resolves the name itself, so the request cannot be bound to
            # an address this side checked. It is made only for a host the
            # configuration trusts by name.
            if self.policy is not ResourcePolicy.ALLOW_ALL and not allowlisted:
                raise ExternalResourceError(f"'{host}' is reached through a proxy, so it has to be listed in {ALLOWED_ORIGINS_VAR}")
            return scheme, host, port, None

        addresses = resolve(host, port)
        if self.policy is ResourcePolicy.BLOCK_INTERNAL and not allowlisted:
            self._check_addresses(addresses, host)
        return scheme, host, port, addresses[0]

    def _proxy_for(self, scheme: str, host: str) -> str | None:
        """The proxy configured for this destination, if any."""
        proxy = getproxies().get(scheme)
        if not proxy or proxy_bypass(host):
            return None
        return proxy

    def _fetch_remote(self, url: str, headers: dict[str, str] | None = None) -> URLFetcherResponse:
        """Load a resource over http, following redirects hop by hop."""
        seen = url
        for _ in range(MAX_REDIRECTS + 1):
            scheme, host, port, address = self._vet(seen)
            response = self._send(scheme, host, port, address, seen, headers)
            location = response.getheader("Location") if response.status in HTTP_REDIRECT_RANGE else None
            if location is None:
                return self._read_response(seen, response)
            # A hop carries no resource, and its body is bounded like any other.
            response.read(self.max_size_bytes)
            response.close()
            seen = urljoin(seen, location)
        raise ExternalResourceError(f"'{url}' redirects more than {MAX_REDIRECTS} times")

    def _send(self, scheme: str, host: str, port: int, address: str | None, url: str, headers: dict[str, str] | None = None) -> http.client.HTTPResponse:
        """Send the request, bound to the address which was vetted."""
        parts = urlsplit(url)
        target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        proxy = self._proxy_for(scheme, host)

        try:
            if proxy:
                connection = self._through_proxy(proxy, scheme, host, port)
                if scheme != "https":
                    target = url
            else:
                connection = self._direct(scheme, host, port, address)

            request_headers = {"User-Agent": "weasyprint-service", **(headers or {})}
            request_headers["Host"] = host_header(host, port, scheme)
            connection.request("GET", target, headers=request_headers)
            return connection.getresponse()
        except ExternalResourceError:
            raise
        except OSError as e:
            raise ExternalResourceError(f"'{url}' could not be loaded: {e}") from e

    def _through_proxy(self, proxy: str, scheme: str, host: str, port: int) -> http.client.HTTPConnection:
        """Open the connection a proxy carries, which resolves the name itself."""
        proxy_parts = urlsplit(proxy if "//" in proxy else f"//{proxy}")
        connection = http.client.HTTPConnection(proxy_parts.hostname or "", proxy_parts.port or DEFAULT_PORTS["http"], timeout=self.timeout_seconds)
        if scheme == "https":
            connection.set_tunnel(host, port)
        return connection

    def _direct(self, scheme: str, host: str, port: int, address: str | None) -> http.client.HTTPConnection:
        """Open the connection to the address which was vetted."""
        if scheme != "https":
            # The name travels in the Host header, never in the address the
            # socket connects to, which is what keeps the request pinned.
            return http.client.HTTPConnection(address or host, port, timeout=self.timeout_seconds)

        # The name is what the certificate is checked against, the address is
        # what the socket connects to.
        context = tls_context()
        connection = http.client.HTTPSConnection(host, port, timeout=self.timeout_seconds, context=context)
        plain_socket = socket.create_connection((address, port), timeout=self.timeout_seconds)
        connection.sock = context.wrap_socket(plain_socket, server_hostname=host)
        return connection

    def _read_response(self, url: str, response: http.client.HTTPResponse) -> URLFetcherResponse:
        """Read a body which is of an allowed kind and within the size limit."""
        with response:
            if response.status != HTTP_OK:
                raise ExternalResourceError(f"'{url}' answered {response.status}")

            declared = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if declared and not declared.startswith(ALLOWED_CONTENT_TYPES) and declared not in UNDECLARED_CONTENT_TYPES:
                raise ExternalResourceError(f"'{url}' is served as '{declared}', which is not an image, a font or a stylesheet")

            body = response.read(self.max_size_bytes + 1)
            if len(body) > self.max_size_bytes:
                raise ExternalResourceError(f"'{url}' is larger than the {self.max_size_bytes // (1024 * 1024)} MB a resource may reach")

            if declared in UNDECLARED_CONTENT_TYPES and not _looks_like_a_resource(body):
                raise ExternalResourceError(f"'{url}' declares no usable content type and its body is not an image or a font")

            headers = {"Content-Type": declared or "application/octet-stream"}
            return URLFetcherResponse(url=url, body=body, headers=headers, status=response.status)


def _looks_like_a_resource(body: bytes) -> bool:
    """Whether a body a server declared nothing about is an image or a font."""
    if body.startswith(CONTENT_SIGNATURES):
        return True
    return body.startswith(RIFF_SIGNATURE) and body[8:12] == WEBP_SIGNATURE
