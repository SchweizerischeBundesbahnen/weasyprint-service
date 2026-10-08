"""Certificates for the TLS tests, made with the openssl command line as an operator would make them."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

CA_CONFIG = """\
[ca]
default_ca = test
[test]
database = index.txt
new_certs_dir = .
serial = serial
default_md = sha256
policy = anything
copy_extensions = copy
[anything]
commonName = supplied
"""


class Pki:
    """Certificates made with the openssl command line, as an operator would make them."""

    def __init__(self, directory: Path) -> None:
        openssl = shutil.which("openssl")
        if not openssl:
            pytest.skip("openssl is not available to produce a certificate")
        self.openssl = openssl
        self.directory = directory

    def _run(self, *args: str) -> None:
        subprocess.run([self.openssl, *args], check=True, capture_output=True, cwd=self.directory)

    def self_signed(self, name: str, san: str | None = None, extended_key_usage: str = "serverAuth") -> tuple[Path, Path]:
        cert, key = self.directory / f"{name}.pem", self.directory / f"{name}.key"
        extensions = ["-addext", f"extendedKeyUsage={extended_key_usage}"]
        if san:
            extensions += ["-addext", f"subjectAltName={san}"]
        self._run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", f"/CN={name}", *extensions)
        return cert, key

    def certificate_authority(self) -> tuple[Path, Path]:
        cert, key = self.directory / "ca.pem", self.directory / "ca.key"
        self._run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=Test CA")
        return cert, key

    def signed(self, name: str, san: str, authority: tuple[Path, Path]) -> tuple[Path, Path]:
        """A certificate the authority signed. The file holds the certificate alone, as the chain is separate."""
        cert, key, request, extensions = (self.directory / f"{name}{suffix}" for suffix in (".pem", ".key", ".csr", ".ext"))
        extensions.write_text(f"subjectAltName={san}\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n", encoding="ascii")
        self._run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(request), "-subj", f"/CN={name}")
        ca_cert, ca_key = authority
        self._run("x509", "-req", "-in", str(request), "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial", "-days", "2", "-extfile", str(extensions), "-out", str(cert))
        return cert, key

    def expired(self, name: str, san: str) -> tuple[Path, Path]:
        """A self-signed certificate which expired in 2020. openssl ca sets the dates on OpenSSL 3.0 as well."""
        cert, key, request = (self.directory / f"{name}{suffix}" for suffix in (".pem", ".key", ".csr"))
        (self.directory / "ca.cnf").write_text(CA_CONFIG, encoding="ascii")
        (self.directory / "index.txt").write_text("", encoding="ascii")
        (self.directory / "serial").write_text("01\n", encoding="ascii")
        self._run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(request), "-subj", f"/CN={name}", "-addext", f"subjectAltName={san}")
        self._run("ca", "-batch", "-config", "ca.cnf", "-selfsign", "-keyfile", str(key), "-in", str(request), "-startdate", "20200101000000Z", "-enddate", "20200102000000Z", "-out", str(cert))
        return cert, key
