#!/bin/bash

if ! pgrep -x 'dbus-daemon' > /dev/null; then
    if [ -f /run/dbus/pid ]; then
        rm /run/dbus/pid
    fi
    dbus_session_bus_address_filename="/tmp/dbus_session_bus_address";
    dbus-daemon --system --fork --print-address > ${dbus_session_bus_address_filename};
    export DBUS_SESSION_BUS_ADDRESS=$(cat ${dbus_session_bus_address_filename})
fi

python app/WeasyprintServiceApplication.py &

wait -n

exit $?