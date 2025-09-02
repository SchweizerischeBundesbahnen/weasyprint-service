#!/bin/bash

BUILD_TIMESTAMP="$(cat /opt/weasyprint/.build_timestamp)"
export WEASYPRINT_SERVICE_BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
CHROMIUM_VERSION="$(${CHROMIUM_EXECUTABLE_PATH} --version | awk '{print $2}')"
export WEASYPRINT_SERVICE_CHROMIUM_VERSION=${CHROMIUM_VERSION}

poetry run python -m app.weasyprint_service_application &

wait -n

exit $?
