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

set -- "${port}"

if [ -n "${cert_file}" ]; then
    # The probe verifies the server like any client of the service would: it
    # trusts this certificate alone and checks it against the name it carries.
    # An expired certificate, or one the server does not present, fails it.
    set -- "$@" "${cert_file}"
    # A server demanding a client certificate rejects the probe without one.
    if [ -n "${probe_cert}" ] || [ -n "${probe_key}" ]; then
        if [ -z "${probe_cert}" ] || [ -z "${probe_key}" ]; then
            echo "TLS_HEALTHCHECK_CERT_FILE and TLS_HEALTHCHECK_KEY_FILE have to be set together" >&2
            exit 1
        fi
        set -- "$@" "${probe_cert}" "${probe_key}"
    fi
fi

# Python is in the image for the service; curl was there for this probe alone.
exec python -I "$(dirname "$0")/app/healthcheck_probe.py" "$@"
