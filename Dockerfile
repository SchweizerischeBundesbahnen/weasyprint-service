FROM python:3.12.4-slim@sha256:fbc51bd56b68084ad398cf601546e7cd0733d6e7c1c62c11cc2c42205efd9127
LABEL maintainer="Team Polarion (CLEW/WZU/POLARION) <polarion@sbb.ch>"

RUN apt-get update && \
    apt-get --yes --no-install-recommends install python3-cffi python3-brotli libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation chromium && \
    apt-get clean autoclean && \
    apt-get --yes autoremove && \
    rm -rf /var/lib/apt/lists/*

ENV WORKING_DIR=/opt/weasyprint
ENV CHROME_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR ${WORKING_DIR}

COPY requirements.txt ${WORKING_DIR}/requirements.txt

RUN pip install --no-cache-dir -r ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/

ENTRYPOINT [ "python", "app/WeasyprintServiceApplication.py" ]
