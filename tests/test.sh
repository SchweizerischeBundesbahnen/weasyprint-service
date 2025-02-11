#!/bin/bash

if [ "$SET_TEST_EXIT_ONE" = "true" ]; then
    exit 1
else
    if [ "$SET_WRITE_OUTPUT" = "true" -a "$9" != "" ]; then
        string="$9"
        arr=(${string//"="/ })
        echo "test" > "${arr[1]}"
        exit 0
    else
        exit 0
    fi
fi
