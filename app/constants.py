import os

# API version for compatibility checking with pdf-exporter.
# Increment this ONLY when making breaking changes to the API contract.
# Minor updates and bug fixes should NOT change this version.
API_VERSION = 1

_TRUTHY_VALUES = ("true", "1", "yes", "on")


def get_bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    return os.environ.get(name, str(default).lower()).lower() in _TRUTHY_VALUES
