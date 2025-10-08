#!/bin/bash

BUILD_TIMESTAMP="$(cat /opt/weasyprint/.build_timestamp)"
export WEASYPRINT_SERVICE_BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Update font cache to include any custom mounted fonts
fc-cache -f

if ! pgrep -x 'dbus-daemon' > /dev/null; then
    mkdir -p "/run/dbus/"
    if [ -f "/run/dbus/pid" ]; then
        rm "/run/dbus/pid"
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

poetry run python -m app.weasyprint_service_application &

wait -n

exit $?
