from __future__ import annotations

import ctypes
import gc
import logging
import os
import platform

logger = logging.getLogger(__name__)

# Environment variable to enable memory reclamation after each conversion
_ENV_VAR = "RECLAIM_MEMORY_AFTER_CONVERSION"
_enabled: bool | None = None


def is_enabled() -> bool:
    """Check if post-conversion memory reclamation is enabled via environment variable."""
    global _enabled  # noqa: PLW0603
    if _enabled is None:
        _enabled = os.environ.get(_ENV_VAR, "false").lower() in ("true", "1", "yes", "on")
        if _enabled:
            logger.info("Post-conversion memory reclamation enabled (%s=true)", _ENV_VAR)
        else:
            logger.info("Post-conversion memory reclamation disabled (set %s=true to enable)", _ENV_VAR)
    return _enabled


def reclaim_memory() -> None:
    """
    Reclaim unused memory after a PDF conversion by running Python garbage
    collection and asking glibc to return free memory to the OS.

    This is a no-op if the feature is disabled or the platform is not Linux (glibc).
    """
    if not is_enabled():
        return

    gc.collect()

    if platform.system() == "Linux":
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
            logger.debug("Memory reclaimed (gc.collect + malloc_trim)")
        except OSError:
            logger.debug("malloc_trim unavailable, skipped (gc.collect only)")
    else:
        logger.debug("Memory reclaimed (gc.collect only, malloc_trim not available on %s)", platform.system())
