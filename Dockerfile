FROM python:3.14.0-slim@sha256:5cfac249393fa6c7ebacaf0027a1e127026745e603908b226baa784c52b9d99b
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>"

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
    procps \
    python3-brotli \
    python3-cffi && \
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

RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

COPY ./requirements.txt ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/
COPY ./app/static/ ${WORKING_DIR}/app/static/
COPY ./pyproject.toml ${WORKING_DIR}/pyproject.toml
COPY ./uv.lock ${WORKING_DIR}/uv.lock

RUN pip install --no-cache-dir -r "${WORKING_DIR}"/requirements.txt && \
    uv sync --frozen --no-dev --no-install-project && \
    uv run playwright install chromium --with-deps

COPY ./entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh

EXPOSE ${PORT}

# Add healthcheck
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9080/health || exit 1

ENTRYPOINT [ "./entrypoint.sh" ]
