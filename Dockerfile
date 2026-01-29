# Copy uv from official image (version matches .tool-versions)
FROM ghcr.io/astral-sh/uv:0.9.28@sha256:59240a65d6b57e6c507429b45f01b8f2c7c0bbeee0fb697c41a39c6a8e3a4cfb AS uv-source

# Use debian:trixie-slim as base (same base as python:3.14-slim)
FROM debian:trixie-slim@sha256:77ba0164de17b88dd0bf6cdc8f65569e6e5fa6cd256562998b62553134a00ef0

# Copy uv binary from source stage
COPY --from=uv-source /uv /usr/local/bin/uv

# Install dependencies
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get --yes --no-install-recommends install \
    curl \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-noto-color-emoji \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    procps && \
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

# Install Python via uv to /opt/python (version from .tool-versions file)
ENV UV_PYTHON_INSTALL_DIR=/opt/python
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN PYTHON_VERSION=$(awk '/^python / {print $2}' .tool-versions) && \
    uv python install "${PYTHON_VERSION}"

# Set Playwright browser path to a shared location (accessible by both root and appuser)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# Install dependencies (as root - venv will be world-readable)
RUN uv sync --frozen --no-dev --no-install-project && \
    uv run playwright install chromium --with-deps

# Create build timestamp
RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

# Copy application code and resources (owned by appuser for potential runtime writes)
COPY --chown=appuser:appuser ./app/*.py ${WORKING_DIR}/app/
COPY --chown=appuser:appuser ./app/static/ ${WORKING_DIR}/app/static/
COPY --chown=appuser:appuser ./app/resources/ ${WORKING_DIR}/app/resources/
COPY --chown=appuser:appuser ./entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh

# Add venv to PATH
ENV PATH="/opt/weasyprint/.venv/bin:$PATH" \
    PYTHONPATH=${WORKING_DIR}

# Verify WeasyPrint is installed and working
RUN weasyprint --version

# Switch to non-root user
USER appuser

EXPOSE ${PORT}
EXPOSE ${METRICS_PORT}

# Add healthcheck
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]

# Security and metadata labels
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>" \
      org.opencontainers.image.title="WeasyPrint Service (Debian)" \
      org.opencontainers.image.description="API service for WeasyPrint document processing" \
      org.opencontainers.image.vendor="SBB" \
      org.opencontainers.image.security.caps.drop="ALL" \
      org.opencontainers.image.security.no-new-privileges="true"
