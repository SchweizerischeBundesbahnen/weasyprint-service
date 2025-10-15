#!/bin/bash

BUILD_TIMESTAMP="$(cat /opt/weasyprint/.build_timestamp)"
export WEASYPRINT_SERVICE_BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Update font cache to include any custom mounted fonts
fc-cache -f

uv run python -m app.weasyprint_service_application &

wait -n

exit $?
