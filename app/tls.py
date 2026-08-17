"""Optional TLS for the servers of this service.

Both servers speak plain HTTP by default, which is what a deployment behind a
reverse proxy or an ingress expects. Where the service is reached directly, each
server can serve TLS instead.

The API server reads ``TLS_*`` and the metrics server reads ``METRICS_TLS_*``.
The two are independent: neither inherits from the other, so the metrics port can
stay plain while the API serves TLS, or the reverse.

An incomplete configuration stops the start, it never falls back to plain HTTP.
Silently serving in the clear while an operator believes otherwise is the one
outcome this must not produce.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any

API_TLS_PREFIX = "TLS_"
METRICS_TLS_PREFIX = "METRICS_TLS_"

CERT_FILE = "CERT_FILE"
KEY_FILE = "KEY_FILE"
CLIENT_CA_FILE = "CLIENT_CA_FILE"
CLIENT_AUTH = "CLIENT_AUTH"

CLIENT_AUTH_MODES = {
    "none": ssl.CERT_NONE,
    "optional": ssl.CERT_OPTIONAL,
    "required": ssl.CERT_REQUIRED,
}


class TlsConfigurationError(ValueError):
    """Raised when the TLS configuration is incomplete or unusable."""


def _read(name: str) -> str:
    """Read an environment value, treating whitespace as unset."""
    return os.environ.get(name, "").strip()


def _readable_file(value: str, name: str) -> str:
    """Return the path, or explain which variable points at an unusable file."""
    path = Path(value)
    if not path.is_file():
        raise TlsConfigurationError(f"{name} points to '{value}', which is not a file")
    try:
        with path.open("rb"):
            pass
    except OSError as e:
        raise TlsConfigurationError(f"{name} points to '{value}', which cannot be read: {e}") from e
    return value


def _client_auth_mode(prefix: str) -> tuple[str, int]:
    """Resolve the client certificate mode, defaulting to no client authentication."""
    configured = _read(prefix + CLIENT_AUTH).lower() or "none"
    if configured not in CLIENT_AUTH_MODES:
        allowed = ", ".join(sorted(CLIENT_AUTH_MODES))
        raise TlsConfigurationError(f"{prefix + CLIENT_AUTH} is '{configured}', expected one of: {allowed}")
    return configured, CLIENT_AUTH_MODES[configured]


def get_tls_options(prefix: str = API_TLS_PREFIX) -> dict[str, Any]:
    """
    Build the TLS keyword arguments for uvicorn from the environment.

    Args:
        prefix: Variable prefix, API_TLS_PREFIX or METRICS_TLS_PREFIX.

    Returns:
        Keyword arguments for uvicorn.run and uvicorn.Config. Empty when TLS is
        not configured, which leaves the server on plain HTTP.

    Raises:
        TlsConfigurationError: When the configuration is incomplete or unusable.
    """
    cert_file = _read(prefix + CERT_FILE)
    key_file = _read(prefix + KEY_FILE)

    if not cert_file and not key_file:
        # A client rule without a certificate would never take effect, so it is
        # reported rather than ignored.
        if _read(prefix + CLIENT_AUTH).lower() not in ("", "none") or _read(prefix + CLIENT_CA_FILE):
            raise TlsConfigurationError(f"{prefix + CLIENT_AUTH} or {prefix + CLIENT_CA_FILE} is configured without {prefix + CERT_FILE} and {prefix + KEY_FILE}")
        return {}

    if not cert_file or not key_file:
        missing = prefix + (CERT_FILE if not cert_file else KEY_FILE)
        raise TlsConfigurationError(f"{missing} is missing, a certificate and its key are both required")

    options: dict[str, Any] = {
        "ssl_certfile": _readable_file(cert_file, prefix + CERT_FILE),
        "ssl_keyfile": _readable_file(key_file, prefix + KEY_FILE),
    }

    # The password is taken as it stands, whitespace included, it is a secret.
    key_password = os.environ.get(prefix + "KEY_PASSWORD")
    if key_password:
        options["ssl_keyfile_password"] = key_password

    mode_name, mode = _client_auth_mode(prefix)
    client_ca_file = _read(prefix + CLIENT_CA_FILE)
    if mode_name == "none":
        if client_ca_file:
            raise TlsConfigurationError(f"{prefix + CLIENT_CA_FILE} is configured while {prefix + CLIENT_AUTH} is 'none', so no client certificate would ever be verified")
    else:
        if not client_ca_file:
            raise TlsConfigurationError(f"{prefix + CLIENT_CA_FILE} is required when {prefix + CLIENT_AUTH} is '{mode_name}'")
        options["ssl_ca_certs"] = _readable_file(client_ca_file, prefix + CLIENT_CA_FILE)
        options["ssl_cert_reqs"] = mode

    return options


def get_scheme(tls_options: dict[str, Any]) -> str:
    """Return the URL scheme the given options serve."""
    return "https" if tls_options else "http"
