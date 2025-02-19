import os
import sys
from pathlib import Path

if os.environ.get("SET_TEST_EXIT_ONE") == "true":
    sys.exit(1)
if os.environ.get("SET_TEST_WRITE_OUTPUT") == "true" and len(sys.argv) > 9 and sys.argv[9]:
    Path(sys.argv[9].split("=")[1]).write_text("test\n")
    sys.exit(0)
else:
    sys.exit(0)
