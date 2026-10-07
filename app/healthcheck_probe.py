"""Probe of the container healthcheck.

healthcheck.sh decides the address and the client certificate, this asks the
service there whether it is healthy. It takes the place of curl, which the image
carried for this probe alone.

The probe talks to its own process over the loopback interface. It does not
verify the certificate of the server, the caller of the service does that, and
it ignores proxy settings: a proxy meant for the requests the service makes must
not carry the probe.

Usage: python -I healthcheck_probe.py URL [CLIENT_CERT_FILE CLIENT_KEY_FILE]
"""

from __future__ import annotations

import ssl
import sys
import urllib.request

ALLOWED_SCHEMES = ("http://", "https://")


def build_opener(cert_file: str | None = None, key_file: str | None = None) -> urllib.request.OpenerDirector:
    """Return an opener which uses no proxy and does not verify the server."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    if cert_file:
        context.load_cert_chain(cert_file, key_file)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))


def probe(url: str, cert_file: str | None = None, key_file: str | None = None) -> None:
    """Return when the service answers with a success status, raise otherwise.

    urllib raises HTTPError for a status of 400 or above, which is where curl
    --fail failed as well.
    """
    if not url.startswith(ALLOWED_SCHEMES):
        raise ValueError(f"The healthcheck only probes http and https, not {url}")
    with build_opener(cert_file, key_file).open(url):
        pass


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 3):
        sys.stderr.write("Usage: healthcheck_probe.py URL [CLIENT_CERT_FILE CLIENT_KEY_FILE]\n")
        return 2
    url, *client = argv
    try:
        probe(url, *client)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
