#!/bin/bash

# Use environment variables with defaults already set in Dockerfile
BUILD_TIMESTAMP="$(cat /opt/weasyprint/.build_timestamp)"
export WEASYPRINT_SERVICE_BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
CHROMIUM_VERSION="$(${CHROMIUM_EXECUTABLE_PATH} --version | awk '{print $2}')"
export WEASYPRINT_SERVICE_CHROMIUM_VERSION=${CHROMIUM_VERSION}

if ! pgrep -x 'dbus-daemon' > /dev/null; then
    if [ -f /run/dbus/pid ]; then
        rm /run/dbus/pid
    fi
    dbus_session_bus_address_filename="/tmp/dbus_session_bus_address";
    dbus-daemon --system --fork --print-address > ${dbus_session_bus_address_filename};

    if [ $? -ne 0 ]; then
        echo "Failed to start dbus-daemon, exiting"
        exit 1
    fi

    BUS_ADDRESS=$(cat ${dbus_session_bus_address_filename});
    export DBUS_SESSION_BUS_ADDRESS=${BUS_ADDRESS};
fi

echo "Starting WeasyPrint service on port $PORT with log level $LOG_LEVEL"

# Convert log level to lowercase for uvicorn
LOG_LEVEL_LOWER=$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')

# Execute the service application with uvicorn for FastAPI
exec uvicorn app.weasyprint_controller:app --host 0.0.0.0 --port $PORT --log-level $LOG_LEVEL_LOWER &

wait -n

exit $?
