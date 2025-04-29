# Builder stage
FROM python:3.13-slim as builder
WORKDIR /app

# Install build dependencies
COPY requirements.txt .
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
    && pip install --no-cache-dir -r requirements.txt \
    && poetry config virtualenvs.create false \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --only main,test

# Final stage
FROM python:3.13.3-slim@sha256:549df749715caa7da8649af1fbf5c0096838a0d69c544dc53c3b3864bfeda4e3
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>" \
      org.opencontainers.image.title="WeasyPrint Service" \
      org.opencontainers.image.description="API service for WeasyPrint document processing" \
      org.opencontainers.image.vendor="SBB"

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends --yes \
    chromium \
    dbus \
    fonts-dejavu \
    fonts-liberation \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    python3-brotli \
    python3-cffi && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ARG APP_IMAGE_VERSION=0.0.0
ENV WORKING_DIR="/opt/weasyprint" \
    CHROMIUM_EXECUTABLE_PATH="/usr/bin/chromium" \
    WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION}

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=${WORKING_DIR} \
    PORT=9080 \
    LOG_LEVEL=INFO

# Create and configure logging directory
RUN mkdir -p ${WORKING_DIR}/logs && \
    chmod 777 ${WORKING_DIR}/logs

WORKDIR ${WORKING_DIR}

# Create build timestamp
RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

# Copy Python dependencies from builder stage
COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy application code
COPY ./app/*.py ${WORKING_DIR}/app/
COPY entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh \
    weasyprint --version  # Verify WeasyPrint is installed and working

EXPOSE ${PORT}
ENTRYPOINT [ "./entrypoint.sh" ]

# Security labels
LABEL org.opencontainers.image.security.caps.drop="ALL"
LABEL org.opencontainers.image.security.no-new-privileges="true"
