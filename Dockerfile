FROM python:3.12.5-slim@sha256:59c7332a4a24373861c4a5f0eec2c92b87e3efeb8ddef011744ef9a751b1d11c
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>"

ARG APP_IMAGE_VERSION

# Architecture from --platform (arm64, amd64 etc.)
ARG TARGETARCH

ARG CHROMIUM_VERSION=126.0.6478.182-1~deb12u1

RUN apt-get update && \
    apt-get --no-install-recommends --yes install fonts-dejavu fonts-liberation libpango-1.0-0 libpangoft2-1.0-0 python3-brotli python3-cffi && \
    # Chromium dependencies
    apt-get --no-install-recommends --yes install \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatomic1 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdav1d6 \
    libdbus-1-3 \
    libdouble-conversion3 \
    libevent-2.1-7 \
    libflac12 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libharfbuzz-subset0 \
    libjpeg62-turbo \
    libjsoncpp25 \
    liblcms2-2 \
    libminizip1 \
    libnss3 \
    libopenh264-7 \
    libopenjp2-7 \
    libopus0 \
    libpulse0 \
    libsnappy1v5 \
    libwoff1 \
    libx11-xcb1 \
    libxdamage1 \
    libxkbcommon0 \
    libxnvctrl0 \
    libxslt1.1 \
    wget \
    x11-utils \
    xdg-utils && \
    # Download Chromium (urls taken from https://snapshot.debian.org/archive/debian/20240820T082737Z/pool/main/c/chromium/)
    wget -P /tmp https://snapshot.debian.org/archive/debian/20240820T082737Z/pool/main/c/chromium/chromium_${CHROMIUM_VERSION}_${TARGETARCH}.deb && \
    wget -P /tmp https://snapshot.debian.org/archive/debian/20240825T022815Z/pool/main/c/chromium/chromium-common_${CHROMIUM_VERSION}_${TARGETARCH}.deb && \
    # Install the downloaded packages
    # DO NOT USE """|| apt-get install -f -y""" COZ THIS CAN FORCE TO UPDATE CHROMIUM TO THE LATEST VERSION
    dpkg -i /tmp/chromium-common_${CHROMIUM_VERSION}_${TARGETARCH}.deb && dpkg -i /tmp/chromium_${CHROMIUM_VERSION}_${TARGETARCH}.deb && \
    # Clean up to reduce image size
    apt-get -y autoremove && \
    apt-get -y clean && \
    rm -rf /tmp/* /var/lib/apt/lists/* /var/tmp/*

ENV WORKING_DIR=/opt/weasyprint
ENV CHROME_EXECUTABLE_PATH=/usr/bin/chromium
ENV WEASYPRINT_SERVICE_VERSION=$APP_IMAGE_VERSION

WORKDIR ${WORKING_DIR}

COPY requirements.txt ${WORKING_DIR}/requirements.txt

RUN pip install --no-cache-dir -r ${WORKING_DIR}/requirements.txt

COPY ./app/*.py ${WORKING_DIR}/app/

ENTRYPOINT [ "python", "app/WeasyprintServiceApplication.py" ]
