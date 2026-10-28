# Copy uv from official image (version matches .tool-versions)
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv-source

# Use debian:trixie-slim as base (same base as python:3.15-slim)
FROM debian:trixie-slim@sha256:89c1ea91e897f0fe0a3731595330bc45b8bdef4047464a07116f891a94054b31

# Copy uv binary from source stage
COPY --from=uv-source /uv /usr/local/bin/uv

# Install dependencies
# libvisio-tools and emf2svg let weasyvsdx draw Visio drawings, Carlito and Caladea replace the Calibri and
# Cambria they ask for. weasyvsdx is tested with libvisio 0.1.7 of trixie; the build checks the release.
# Symbola draws the symbols Word documents take from Wingdings and Symbol. Each font package keeps its license
# in /usr/share/doc/<package>/copyright.
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get --yes --no-install-recommends install \
    emf2svg \
    fonts-crosextra-caladea \
    fonts-crosextra-carlito \
    fonts-dejavu \
    fonts-freefont-ttf \
    fonts-ipafont-gothic \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-noto-color-emoji \
    fonts-symbola \
    fonts-tlwg-loma-otf \
    fonts-unifont \
    fonts-wqy-zenhei \
    libharfbuzz-subset0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libvisio-tools && \
    test "$(vsd2xhtml --version)" = "vsd2xhtml 0.1.7" && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ARG APP_IMAGE_VERSION=0.0.0
ENV WORKING_DIR="/opt/weasyprint" \
    WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION} \
    PORT=9080 \
    METRICS_PORT=9180 \
    LOG_LEVEL=INFO

# Create non-root user early (before creating directories that need ownership)
RUN useradd -u 1000 -m -s /bin/bash appuser

# Create and configure logging directory (owned by appuser)
RUN mkdir -p ${WORKING_DIR}/logs && \
    chown appuser:appuser ${WORKING_DIR}/logs && \
    chmod 777 ${WORKING_DIR}/logs && \
    mkdir -p /tmp/strictdoc && \
    chown -R appuser:appuser /tmp/strictdoc

WORKDIR ${WORKING_DIR}

# Copy Python version file and dependency files
COPY .tool-versions pyproject.toml uv.lock ./

# Install Python via uv to /opt/python (version from .tool-versions file).
# pip comes with it, and nothing in the image uses it: uv installs the packages.
# Removed here, so the scanners do not report the packages it vendors.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN PYTHON_VERSION=$(awk '/^python / {print $2}' .tool-versions) && \
    uv python install --no-cache "${PYTHON_VERSION}" && \
    rm -rf /opt/python/*/lib/python3.*/site-packages/pip* /opt/python/*/lib/python3.*/ensurepip/_bundled /opt/python/*/bin/pip*

# The image has no compiler, so every package installs from a wheel: --no-build
# fails the build on a package without one for this Python. --no-cache keeps the
# downloads out of the image, the venv holds what runs.
RUN uv sync --frozen --no-dev --no-install-project --no-build --no-cache

# Create build timestamp
RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

# Copy application code and resources (owned by appuser for potential runtime writes)
COPY --chown=appuser:appuser ./app/*.py ${WORKING_DIR}/app/
COPY --chown=appuser:appuser ./app/static/ ${WORKING_DIR}/app/static/
COPY --chown=appuser:appuser ./app/resources/ ${WORKING_DIR}/app/resources/
COPY --chown=appuser:appuser ./entrypoint.sh ${WORKING_DIR}/entrypoint.sh
COPY --chown=appuser:appuser ./healthcheck.sh ${WORKING_DIR}/healthcheck.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh ${WORKING_DIR}/healthcheck.sh

# Add venv to PATH
ENV PATH="/opt/weasyprint/.venv/bin:$PATH" \
    PYTHONPATH=${WORKING_DIR}

# Replace the German hyphenation dictionaries bundled with Pyphen (LibreOffice
# patterns, frozen at 2017-01-12) with the newer dehyph-exptl patterns
# (dehyphn-x 2024-02-28). These fix single-letter mis-hyphenation such as
# "Über-g-ang" -> "Über-gang" and cover reformed orthography for DE/AT/CH.
# The same reformed pattern set is used for de_DE, de_AT and de_CH. The MIT
# notice is shipped alongside the data (dehyph-exptl requires it to travel with
# redistributed copies, which the image is).
COPY dictionaries/hyph_de_dehyphn-x-2024-02-28.dic ${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic
COPY dictionaries/LICENSE.dehyph-exptl ${WORKING_DIR}/dictionaries/LICENSE.dehyph-exptl
RUN DICT_DIR="$(python -c 'import os, pyphen; print(os.path.dirname(str(pyphen.LANGUAGES["de_DE"])))')" && \
    cp "${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic" "${DICT_DIR}/hyph_de_DE.dic" && \
    cp "${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic" "${DICT_DIR}/hyph_de_AT.dic" && \
    cp "${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic" "${DICT_DIR}/hyph_de_CH.dic"

# Verify WeasyPrint is installed and working
RUN weasyprint --version

# Selawik, the open fallback Microsoft made for Segoe UI, which Visio drawings ask for. Debian has no
# package of it: the release of microsoft/Selawik, checked by its SHA-256. Its fonts carry no license text,
# which the SIL Open Font License asks to travel with each copy, so the license of the release goes along.
ADD --checksum=sha256:3f62c51e05e3b5a1e6241cf92a371f0be2ea1183aa87b30718bbd40832a8d423 \
    https://github.com/microsoft/Selawik/releases/download/1.01/Selawik_Release.zip /tmp/selawik.zip
ADD --checksum=sha256:77b7c2506d4efb22e09c8ccf10159f4956eab3ef7c007fef95de136bcf45300c \
    https://raw.githubusercontent.com/microsoft/Selawik/1.01/LICENSE.txt /usr/local/share/fonts/selawik/LICENSE.txt
RUN python -c "import zipfile; archive = zipfile.ZipFile('/tmp/selawik.zip'); archive.extractall('/usr/local/share/fonts/selawik', [name for name in archive.namelist() if name.endswith('.ttf')])" && \
    chmod 644 /usr/local/share/fonts/selawik/LICENSE.txt && \
    rm /tmp/selawik.zip && \
    fc-cache --force && \
    test -n "$(fc-list Selawik)" && test -n "$(fc-list Carlito)"

# Switch to non-root user (numeric uid:gid of appuser, resolvable by any host)
USER 1000:1000

EXPOSE ${PORT}
EXPOSE ${METRICS_PORT}

# Add healthcheck
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["/bin/sh", "-c", "./healthcheck.sh || exit 1"]

ENTRYPOINT ["./entrypoint.sh"]

# Security and metadata labels
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>" \
      org.opencontainers.image.title="WeasyPrint Service (Debian)" \
      org.opencontainers.image.description="API service for WeasyPrint document processing" \
      org.opencontainers.image.vendor="SBB" \
      org.opencontainers.image.security.caps.drop="ALL" \
      org.opencontainers.image.security.no-new-privileges="true"
