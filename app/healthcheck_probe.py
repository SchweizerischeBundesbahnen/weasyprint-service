"""Probe of the container healthcheck.

healthcheck.sh passes the port of the service, and the certificate files where
the service serves TLS. The probe asks the service whether it is healthy, and
over TLS it verifies the server the way any client of the service would.

It trusts exactly the certificate the service is configured to present, so the
image needs no CA for it, and it checks that certificate against the first name
it carries. The connection goes to the loopback interface, whatever that name
resolves to elsewhere. A certificate which has expired, or which is not the one
the server presents, fails the probe: a client of the service would fail on it
as well.

The probe uses no proxy: http.client connects directly, and a proxy meant for the
requests the service makes must not carry the probe.

Usage: python -I healthcheck_probe.py PORT [SERVER_CERT_FILE [CLIENT_CERT_FILE CLIENT_KEY_FILE]]
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

LOOPBACK = "127.0.0.1"
HEALTH_PATH = "/health"
# The healthcheck of the image gives the probe 3 seconds
TIMEOUT_SECONDS = 3.0
USAGE = "Usage: healthcheck_probe.py PORT [SERVER_CERT_FILE [CLIENT_CERT_FILE CLIENT_KEY_FILE]]\n"

PEM_BEGIN = b"-----BEGIN CERTIFICATE-----"
PEM_END = b"-----END CERTIFICATE-----"

# DER tags of the parts of a certificate the probe reads
SEQUENCE = 0x30
OBJECT_IDENTIFIER = 0x06
OCTET_STRING = 0x04
EXTENSIONS = 0xA3  # [3] EXPLICIT, the extensions of a version 3 certificate
DNS_NAME = 0x82  # [2] IMPLICIT IA5String, a GeneralName
IP_ADDRESS = 0x87  # [7] IMPLICIT OCTET STRING, a GeneralName
SUBJECT_ALT_NAME = bytes([0x55, 0x1D, 0x11])  # 2.5.29.17
# A tag and a length octet open every element
HEADER_OCTETS = 2
HIGH_TAG_NUMBER = 0x1F
LONG_LENGTH = 0x80
MAX_LENGTH_OCTETS = 4

# A wildcard names no host. Any label in its place matches it.
WILDCARD_LABEL = "healthcheck"


class UnhealthyError(Exception):
    """The service answered, with a status which is no success."""


def _elements(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield the tag and the content of each DER element in data, in order."""
    offset = 0
    while offset < len(data):
        if len(data) - offset < HEADER_OCTETS:
            raise ValueError("The certificate ends inside an element")
        tag, length = data[offset], data[offset + 1]
        offset += HEADER_OCTETS
        if tag & HIGH_TAG_NUMBER == HIGH_TAG_NUMBER:
            raise ValueError("The certificate has a tag the probe does not read")
        if length & LONG_LENGTH:
            octets = length & (LONG_LENGTH - 1)
            # An indefinite length is not DER, and no part of a certificate needs more than 4 octets
            if not 0 < octets <= MAX_LENGTH_OCTETS or offset + octets > len(data):
                raise ValueError("The certificate has a length the probe does not read")
            length = int.from_bytes(data[offset : offset + octets], "big")
            offset += octets
        end = offset + length
        if end > len(data):
            raise ValueError("The certificate ends inside an element")
        yield tag, data[offset:end]
        offset = end


def _first(data: bytes, tag: int) -> bytes:
    """Return the content of the first element of data, which has to carry tag."""
    for found, content in _elements(data):
        if found != tag:
            break
        return content
    raise ValueError("The certificate is not built the way a certificate is")


def _extensions(der: bytes) -> Iterator[list[tuple[int, bytes]]]:
    """Yield the parts of each extension of a DER certificate.

    Certificate ::= SEQUENCE { tbsCertificate, signatureAlgorithm, signature }, and the
    extensions are the [3] element of tbsCertificate.
    """
    tbs_certificate = _first(_first(der, SEQUENCE), SEQUENCE)
    for tag, content in _elements(tbs_certificate):
        if tag == EXTENSIONS:
            for _, extension in _elements(_first(content, SEQUENCE)):
                # Extension ::= SEQUENCE { extnID, critical BOOLEAN DEFAULT FALSE, extnValue OCTET STRING }
                yield list(_elements(extension))


def _general_names(value_tag: int, value: bytes) -> list[tuple[str, str]]:
    """Return the DNS names and IP addresses of the value of a subjectAltName. Other kinds of name are skipped."""
    if value_tag != OCTET_STRING:
        raise ValueError("The subjectAltName of the certificate is not built the way it is defined")
    names: list[tuple[str, str]] = []
    for name_tag, name in _elements(_first(value, SEQUENCE)):
        if name_tag == DNS_NAME:
            names.append(("DNS", name.decode("ascii")))
        elif name_tag == IP_ADDRESS:
            names.append(("IP", str(ipaddress.ip_address(name))))
    return names


def subject_alt_names(der: bytes) -> list[tuple[str, str]]:
    """Return the DNS names and IP addresses of the subjectAltName of a DER certificate."""
    for parts in _extensions(der):
        if parts and parts[0] == (OBJECT_IDENTIFIER, SUBJECT_ALT_NAME):
            return _general_names(*parts[-1])
    return []


def read_certificate(cert_file: str) -> bytes:
    """Return the first certificate of a PEM file as DER. A chain starts with the certificate of the server.

    Only the block is decoded. OpenSSL skips the text around it, which need not be ASCII:
    openssl pkcs12 writes the attributes of each certificate there, a friendly name among them.
    """
    data = Path(cert_file).read_bytes()
    start = data.find(PEM_BEGIN)
    end = data.find(PEM_END, start)
    if start < 0 or end < 0:
        raise ValueError(f"{cert_file} holds no PEM certificate")
    return ssl.PEM_cert_to_DER_cert(data[start : end + len(PEM_END)].decode("ascii"))


def server_name(cert_file: str) -> str:
    """Return the name the probe checks the certificate of the server against.

    The first DNS name of the subjectAltName, with a concrete label for a wildcard, or the
    first IP address where the certificate names no host. The common name does not count:
    a hostname check ignores it, as browsers do.
    """
    names = subject_alt_names(read_certificate(cert_file))
    dns_names = [name for kind, name in names if kind == "DNS"]
    if dns_names:
        name = dns_names[0]
        return f"{WILDCARD_LABEL}{name[1:]}" if name.startswith("*.") else name
    if names:
        # Only addresses are left
        return names[0][1]
    raise ValueError(f"{cert_file} names no host in its subjectAltName, so no client can verify the server")


class LoopbackHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection to the loopback interface, which verifies the server against another name."""

    def __init__(self, name: str, port: int, context: ssl.SSLContext) -> None:
        super().__init__(name, port, timeout=TIMEOUT_SECONDS, context=context)
        self.tls_context = context

    def connect(self) -> None:
        sock = socket.create_connection((LOOPBACK, self.port), self.timeout)
        self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)


def probe(port: int, server_cert: str | None = None, client_cert: str | None = None, client_key: str | None = None) -> None:
    """Return when the service answers with a success status, raise otherwise.

    A status of 400 or above fails the probe, as curl --fail did before it.
    """
    connection: http.client.HTTPConnection
    if server_cert is None:
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=TIMEOUT_SECONDS)
    else:
        # Read first: a file without a usable certificate is reported as such, not as a failed handshake
        name = server_name(server_cert)
        # The certificate of the server is the only one trusted, and the hostname and chain checks stay on
        context = ssl.create_default_context(cafile=server_cert)
        # Python adds checks no common client makes: a CA without a keyUsage extension, as
        # openssl req -x509 makes it, fails them, while curl and browsers accept it
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        if client_cert:
            context.load_cert_chain(client_cert, client_key)
        connection = LoopbackHTTPSConnection(name, port, context)
    try:
        connection.request("GET", HEALTH_PATH)
        response = connection.getresponse()
        if response.status >= http.HTTPStatus.BAD_REQUEST:
            raise UnhealthyError(f"The service answered {response.status} {response.reason}")
    finally:
        connection.close()


def parse_port(value: str) -> int:
    port = int(value)
    if not 0 < port < 2**16:
        raise ValueError(f"{value} is no port")
    return port


def main(argv: list[str]) -> int:
    # PORT, PORT SERVER_CERT, or PORT SERVER_CERT CLIENT_CERT CLIENT_KEY
    if len(argv) not in (1, 2, 4):
        sys.stderr.write(USAGE)
        return 2
    try:
        port = parse_port(argv[0])
    except ValueError:
        sys.stderr.write(USAGE)
        return 2
    try:
        probe(port, *argv[1:])
    except (OSError, ValueError, UnhealthyError, http.client.HTTPException) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
