# Copy uv from official image (version matches .tool-versions)
FROM ghcr.io/astral-sh/uv:0.9.16@sha256:ae9ff79d095a61faf534a882ad6378e8159d2ce322691153d68d2afac7422840 AS uv-source

# Use debian:trixie-slim as base (same base as python:3.14-slim)
FROM debian:trixie-slim@sha256:e711a7b30ec1261130d0a121050b4ed81d7fb28aeabcf4ea0c7876d4e9f5aca2

LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>"

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
    LOG_LEVEL=INFO

# Create and configure logging directory
RUN mkdir -p ${WORKING_DIR}/logs && \
    chmod 777 ${WORKING_DIR}/logs

WORKDIR ${WORKING_DIR}

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python via uv and dependencies
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv python install 3.14 && \
    uv sync --frozen --no-dev --no-install-project && \
    uv run playwright install chromium --with-deps

# Create build timestamp
RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

# Copy application code and resources
COPY ./app/*.py ${WORKING_DIR}/app/
COPY ./app/static/ ${WORKING_DIR}/app/static/
COPY ./app/resources/ ${WORKING_DIR}/app/resources/
COPY ./entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh

# Add venv to PATH
ENV PATH="/opt/weasyprint/.venv/bin:$PATH" \
    PYTHONPATH=${WORKING_DIR}

# Verify WeasyPrint is installed and working
RUN weasyprint --version

# Make Python installation readable by all users
RUN chmod -R a+rX /opt/python && \
    chmod -R a+rx ${WORKING_DIR}/.venv/bin

EXPOSE ${PORT}

# Add healthcheck
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9080/health || exit 1

ENTRYPOINT [ "./entrypoint.sh" ]
