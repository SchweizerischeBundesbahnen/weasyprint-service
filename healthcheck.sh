#!/bin/sh
# Docker healthcheck. Follows the scheme the API server was configured with.
set -eu

# Strip surrounding whitespace. app/tls.py reads a blank value as unset, and the
# probe has to reach the same verdict, or it would ask for a scheme the server
# does not serve.
trim() {
    trimmed="$1"
    trimmed="${trimmed#"${trimmed%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
    printf '%s' "${trimmed}"
}

port="$(trim "${PORT:-9080}")"
cert_file="$(trim "${TLS_CERT_FILE:-}")"
probe_cert="$(trim "${TLS_HEALTHCHECK_CERT_FILE:-}")"
probe_key="$(trim "${TLS_HEALTHCHECK_KEY_FILE:-}")"

url="http://localhost:${port}/health"
set --

if [ -n "${cert_file}" ]; then
    url="https://localhost:${port}/health"
    # The certificate is verified by the caller of the service, not here: this
    # probe talks to its own process over the loopback interface and asks one
    # question, whether that process still answers.
    set -- --insecure
    # A server demanding a client certificate rejects the probe without one.
    if [ -n "${probe_cert}" ] || [ -n "${probe_key}" ]; then
        if [ -z "${probe_cert}" ] || [ -z "${probe_key}" ]; then
            echo "TLS_HEALTHCHECK_CERT_FILE and TLS_HEALTHCHECK_KEY_FILE have to be set together" >&2
            exit 1
        fi
        set -- "$@" --cert "${probe_cert}" --key "${probe_key}"
    fi
fi

exec curl --fail --silent --show-error "$@" "${url}"
