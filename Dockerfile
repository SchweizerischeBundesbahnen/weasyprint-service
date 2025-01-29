# hadolint global ignore=DL3008
FROM python:3.13.1-slim@sha256:23a81be7b258c8f516f7a60e80943cace4350deb8204cf107c7993e343610d47
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>"

ARG APP_IMAGE_VERSION=0.0.0-dev

RUN apt-get update && \
    apt-get --yes --no-install-recommends install \
    chromium dbus \
    fonts-dejavu \
    fonts-liberation \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    python3-brotli \
    python3-cffi \
    vim && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ENV WORKING_DIR="/opt/weasyprint"
ENV CHROMIUM_EXECUTABLE_PATH="/usr/bin/chromium"
ENV WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION}

WORKDIR ${WORKING_DIR}

RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

COPY requirements.txt ${WORKING_DIR}/requirements.txt

RUN pip install --no-cache-dir -r ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/

COPY entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh

ENTRYPOINT [ "./entrypoint.sh" ]
