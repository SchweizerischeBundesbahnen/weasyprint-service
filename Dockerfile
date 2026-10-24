# Copy uv from official image (version matches .tool-versions)
FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv-source

# Python and the virtual environment are built in a stage of their own, which has
# a C compiler: a package without a wheel for this Python (brotli for 3.15)
# builds from source here. The final image takes only the result.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS venv
COPY --from=uv-source /uv /usr/local/bin/uv
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get --yes --no-install-recommends install gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

ENV WORKING_DIR="/opt/weasyprint"
WORKDIR ${WORKING_DIR}

# Copy Python version file and dependency files
COPY .tool-versions pyproject.toml uv.lock ./

# Install Python via uv to /opt/python (version from .tool-versions file).
# pip comes with it, and nothing in the image uses it: uv installs the packages.
# Removed here, so the scanners do not report the packages it vendors.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN PYTHON_VERSION=$(awk '/^python / {print $2}' .tool-versions) && \
    uv python install "${PYTHON_VERSION}" && \
    rm -rf /opt/python/*/lib/python3.*/site-packages/pip* /opt/python/*/lib/python3.*/ensurepip/_bundled /opt/python/*/bin/pip*

# The venv links to the Python in /opt/python, so both keep their paths below
RUN uv sync --frozen --no-dev --no-install-project

# Use debian:trixie-slim as base (same base as python:3.15-slim)
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# Copy uv binary from source stage
COPY --from=uv-source /uv /usr/local/bin/uv

# Install dependencies
# libvisio-tools and emf2svg let weasyvsdx draw Visio drawings, Carlito and Caladea replace the Calibri and
# Cambria they ask for. weasyvsdx is tested with libvisio 0.1.7 of trixie; the build checks the release.
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
    fonts-tlwg-loma-otf \
    fonts-unifont \
    fonts-wqy-zenhei \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libdrm2 \
    libgbm1 \
    libnspr4 \
    libnss3 \
    libharfbuzz-subset0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libvisio-tools \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    procps \
    xfonts-scalable && \
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

# Python and the venv from the venv stage, without its compiler
ENV UV_PYTHON_INSTALL_DIR=/opt/python
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY --from=venv /opt/python /opt/python
COPY --from=venv ${WORKING_DIR}/.venv ${WORKING_DIR}/.venv

# Set Playwright browser path to a shared location (accessible by both root and appuser)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# Install the browser (as root - it will be world-readable)
# Playwright runs with --no-sync: a plain "uv run" syncs the default groups
# again and would put the dev group (ruff, ty, pre-commit) into the image.
# No --with-deps: it would add xvfb, an X server for headed browsers, while the
# service runs Chromium headless. The libraries and fonts Playwright lists for
# Chromium are installed with the system packages above.
# --only-shell: the service launches the headless shell, the full browser is
# never started and is the only one to need libcups2 and libcairo2.
RUN uv run --no-sync playwright install --only-shell chromium

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
# package of it: the release of microsoft/Selawik, checked by its SHA-256.
ADD --checksum=sha256:3f62c51e05e3b5a1e6241cf92a371f0be2ea1183aa87b30718bbd40832a8d423 \
    https://github.com/microsoft/Selawik/releases/download/1.01/Selawik_Release.zip /tmp/selawik.zip
RUN python -c "import zipfile; zipfile.ZipFile('/tmp/selawik.zip').extractall('/usr/local/share/fonts/selawik')" && \
    rm /tmp/selawik.zip && \
    fc-cache --force && \
    test -n "$(fc-list Selawik)" && test -n "$(fc-list Carlito)"

# Who draws SVG by default: chromium (PNG through the browser) or weasysvg (vector, by WeasyPrint)
ARG SVG_RENDERER=weasysvg
ENV SVG_RENDERER=${SVG_RENDERER}

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
