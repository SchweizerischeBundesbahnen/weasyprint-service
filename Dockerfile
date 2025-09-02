FROM python:3.13.7-slim@sha256:27f90d79cc85e9b7b2560063ef44fa0e9eaae7a7c3f5a9f74563065c5477cc24
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>"

ARG APP_IMAGE_VERSION=0.0.0

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get --yes --no-install-recommends install \
    chromium \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-noto-color-emoji \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    python3-brotli \
    python3-cffi && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ENV WORKING_DIR="/opt/weasyprint"
ENV CHROMIUM_EXECUTABLE_PATH="/usr/bin/chromium"
ENV WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION}

# Create and configure logging directory
RUN mkdir -p ${WORKING_DIR}/logs && \
    chmod 777 ${WORKING_DIR}/logs

WORKDIR ${WORKING_DIR}

RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

COPY requirements.txt ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/
COPY ./pyproject.toml ${WORKING_DIR}/pyproject.toml
COPY ./poetry.lock ${WORKING_DIR}/poetry.lock

RUN pip install --no-cache-dir -r "${WORKING_DIR}"/requirements.txt && poetry install --no-root --only main

COPY entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh

ENTRYPOINT [ "./entrypoint.sh" ]
