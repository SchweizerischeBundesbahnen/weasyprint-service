#!/bin/bash

BUILD_TIMESTAMP="$(cat /opt/weasyprint/.build_timestamp)"
export WEASYPRINT_SERVICE_BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Update font cache to include any custom mounted fonts
fc-cache -f

# The --no-sync flag is used because all dependencies are installed during the image build process.
# The environment is assumed to be already synchronized, so runtime sync is unnecessary and skipped for faster startup.
#
# exec replaces this shell with the server process, so "docker stop" delivers SIGTERM to it
# instead of to a shell which would not forward the signal. uv passes the signal on to Python,
# uvicorn stops accepting requests and runs the shutdown hooks which close the metrics server
# and the Chromium browser.
exec uv run --no-sync python -m app.weasyprint_service_application
