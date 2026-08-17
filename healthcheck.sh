#!/bin/sh
# Docker healthcheck. Follows the scheme the API server was configured with.
set -eu

port="${PORT:-9080}"
url="http://localhost:${port}/health"
set --

if [ -n "${TLS_CERT_FILE:-}" ]; then
    url="https://localhost:${port}/health"
    # The certificate is verified by the caller of the service, not here: this
    # probe talks to its own process over the loopback interface and asks one
    # question, whether that process still answers.
    set -- --insecure
    # A server demanding a client certificate rejects the probe without one.
    if [ -n "${TLS_HEALTHCHECK_CERT_FILE:-}" ] && [ -n "${TLS_HEALTHCHECK_KEY_FILE:-}" ]; then
        set -- "$@" --cert "${TLS_HEALTHCHECK_CERT_FILE}" --key "${TLS_HEALTHCHECK_KEY_FILE}"
    fi
fi

exec curl --fail --silent --show-error "$@" "${url}"
