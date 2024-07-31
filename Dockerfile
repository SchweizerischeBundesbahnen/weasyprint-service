FROM python:3.12.4-slim@sha256:740d94a19218c8dd584b92f804b1158f85b0d241e5215ea26ed2dcade2b9d138
LABEL maintainer="Team Polarion (CLEW/WZU/POLARION) <polarion@sbb.ch>"
ARG APP_VERSION

RUN apt-get update && \
    apt-get --yes --no-install-recommends install python3-cffi python3-brotli libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation chromium && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ENV WORKING_DIR=/opt/weasyprint
ENV CHROME_EXECUTABLE_PATH=/usr/bin/chromium
ENV WEASYPRINT_SERVICE_VERSION=$APP_VERSION

WORKDIR ${WORKING_DIR}

COPY requirements.txt ${WORKING_DIR}/requirements.txt

RUN pip install --no-cache-dir -r ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/

ENTRYPOINT [ "python", "app/WeasyprintServiceApplication.py" ]
