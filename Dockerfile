FROM python:3.13.1-slim@sha256:f41a75c9cee9391c09e0139f7b49d4b1fbb119944ec740ecce4040626dc07bed
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>"

ARG APP_IMAGE_VERSION=0.0.0

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get --yes --no-install-recommends install \
    chromium \
    dbus \
    upower \
    fonts-dejavu \
    fonts-liberation \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    python3-brotli \
    python3-cffi \
    imagemagick \
    vim && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ENV WORKING_DIR="/opt/weasyprint"
ENV CHROMIUM_EXECUTABLE_PATH="/usr/bin/chromium"
ENV CONVERT_EXECUTABLE_PATH="/usr/bin/convert"
ENV WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION}

WORKDIR ${WORKING_DIR}

RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

COPY requirements.txt ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/
COPY ./pyproject.toml ${WORKING_DIR}/pyproject.toml
COPY ./poetry.lock ${WORKING_DIR}/poetry.lock

RUN pip install --no-cache-dir -r "${WORKING_DIR}"/requirements.txt && poetry install --no-root && poetry env activate

COPY entrypoint.sh ${WORKING_DIR}/entrypoint.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh

ENTRYPOINT [ "./entrypoint.sh" ]
