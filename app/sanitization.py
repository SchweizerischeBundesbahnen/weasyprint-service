"""Utilities for input sanitization in the WeasyPrint service."""

import re
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


def sanitize_path_for_logging(path: str | None, show_basename_only: bool = True) -> str:
    """Sanitize file path for safe logging by optionally showing only basename.

    Args:
        path: The file path to sanitize. If None, returns 'None'.
        show_basename_only: If True, only show the filename (not full path).

    Returns:
        str: Sanitized path string.

    """
    if path is None:
        return "None"

    try:
        path_obj = Path(path)
        if show_basename_only:
            return sanitize_for_logging(path_obj.name, max_length=100)
        # Show relative path if inside temp directory (using tempfile module would be better but this is simpler for logging)
        if str(path).startswith("/tmp/") or "\\temp\\" in str(path).lower():  # noqa: S108
            return sanitize_for_logging(f"<temp>/{path_obj.name}", max_length=150)
        return sanitize_for_logging(str(path), max_length=200)
    except Exception:
        return sanitize_for_logging(str(path), max_length=200)
