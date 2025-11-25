#!/bin/bash

BUILD_TIMESTAMP="$(cat /opt/weasyprint/.build_timestamp)"
export WEASYPRINT_SERVICE_BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Update font cache to include any custom mounted fonts
fc-cache -f

# The --no-sync flag is used because all dependencies are installed during the image build process.
# The environment is assumed to be already synchronized, so runtime sync is unnecessary and skipped for faster startup.
uv run --no-sync python -m app.weasyprint_service_application &

wait -n

exit $?
