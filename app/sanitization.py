"""Utilities for input sanitization in the WeasyPrint service."""

import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse


def sanitize_for_logging(text: str, max_length: int = 1000) -> str:
    """Sanitize text for safe logging by:
    - Converting non-string input to string
    - Removing all control characters
    - Replacing newlines with spaces
    - Truncating to `max_length` and appending '...[truncated]' if necessary

    Args:
        text (str): The input text to sanitize.
        max_length (int, optional): Maximum allowed length of the sanitized text. Defaults to 1000.

    Returns:
        str: The sanitized text safe for logging.

    """
    if not isinstance(text, str):
        text = str(text)

    # Replace newlines with spaces first (before removing other control characters)
    text = text.replace("\n", " ").replace("\r", " ")

    # Remove all other control characters
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)

    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length] + "...[truncated]"

    return text


def sanitize_url_for_logging(url: str | None) -> str:
    """Sanitize URL for safe logging by removing sensitive query parameters and credentials.

    Args:
        url: The URL to sanitize. If None, returns 'None'.

    Returns:
        str: Sanitized URL with query parameters and credentials removed.

    """
    if url is None:
        return "None"

    try:
        parsed = urlparse(url)
        # Reconstruct URL without query parameters and credentials
        safe_url = f"{parsed.scheme}://{parsed.hostname or ''}"
        if parsed.port:
            safe_url += f":{parsed.port}"
        safe_url += parsed.path or "/"
        return sanitize_for_logging(safe_url, max_length=200)
    except Exception:
        # Fallback to generic sanitization if URL parsing fails
        return sanitize_for_logging(url, max_length=200)


def sanitize_path_for_logging(path: str | None, show_basename_only: bool = True) -> str:  # noqa: PLR0911
    """Sanitize file path for safe logging by optionally showing only basename.

    This function is for DISPLAY/LOGGING purposes only - it does not perform any file I/O operations.
    It detects temp directory paths in the input string to anonymize them in log output.

    Args:
        path: The file path to sanitize. If None, returns 'None'.
        show_basename_only: If True, only show the filename (not full path).

    Returns:
        str: Sanitized path string safe for logging.

    """
    if path is None:
        return "None"

    try:
        path_obj = Path(path)
        if show_basename_only:
            return sanitize_for_logging(path_obj.name, max_length=100)

        # Use tempfile module to safely detect system temp directory
        system_temp_dir = Path(tempfile.gettempdir()).resolve()
        path_str = str(path)

        # Check if path is inside temp directory
        try:
            # Try to resolve if path exists
            if path_obj.exists():
                check_path = path_obj.resolve()
                check_path.relative_to(system_temp_dir)
                return sanitize_for_logging(f"<temp>/{path_obj.name}", max_length=150)

            # For non-existent paths, check if path string indicates temp directory
            # S108: Hardcoded paths are safe here - we're pattern matching for display only, not performing file operations
            if path_str.startswith("/tmp/"):  # noqa: S108
                normalized_path = Path(path_str.replace("/tmp/", str(system_temp_dir) + "/", 1))  # noqa: S108
                normalized_path.relative_to(system_temp_dir)
                return sanitize_for_logging(f"<temp>/{path_obj.name}", max_length=150)

            # Handle Windows-style temp paths (case-insensitive)
            if path_str.lower().startswith("c:\\temp\\") or path_str.lower().startswith("c:/temp/"):
                return sanitize_for_logging(f"<temp>/{path_obj.name}", max_length=150)

            # Not a temp path
            return sanitize_for_logging(str(path), max_length=200)
        except (ValueError, OSError):
            # Path is not in temp directory - return sanitized full path
            return sanitize_for_logging(str(path), max_length=200)
    except Exception:
        return sanitize_for_logging(str(path), max_length=200)
