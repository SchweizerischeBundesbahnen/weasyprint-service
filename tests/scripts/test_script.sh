#!/bin/bash

if [ "$WEASYPRINT_SERVICE_TEST_EXIT_ONE" = "true" ]; then
    exit 1
fi
if [ "$WEASYPRINT_SERVICE_TEST_WRITE_OUTPUT" = "true" -a "$9" != "" ]; then
    string="$9"
    arr=(${string//"="/ })
    echo "test" > "${arr[1]}"
fi
exit 0
