#!/bin/bash

if ! pgrep -x 'dbus-daemon' > /dev/null; then
    if [ -f /run/dbus/pid ]; then
        rm /run/dbus/pid
    fi
    dbus-daemon --system --fork;
fi

python app/WeasyprintServiceApplication.py &

wait -n

exit $?