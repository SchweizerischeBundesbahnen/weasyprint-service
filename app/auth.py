"""Optional API key authentication for the WeasyPrint service.

Authentication is disabled by default. It activates when the ``API_KEY``
environment variable holds at least one non-empty key. Several keys can be
configured as a comma-separated list, which allows key rotation without
downtime.

Clients send the key in one of two headers:

- ``X-API-Key: <key>``
- ``Authorization: Bearer <key>``
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "API_KEY"
API_KEY_HEADER_NAME = "X-API-Key"

_UNAUTHORIZED_MESSAGE = "Invalid or missing API key"

# auto_error=False keeps both schemes optional, so a missing header reaches
# require_api_key instead of failing inside the security dependency.
_api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False, description="API key, required when the service is started with API_KEY configured.")
_bearer_scheme = HTTPBearer(auto_error=False, description="API key sent as a bearer token, required when the service is started with API_KEY configured.")


def get_api_keys() -> tuple[str, ...]:
    """
    Read the configured API keys from the environment.

    Returns:
        Tuple of non-empty keys parsed from the API_KEY variable. Empty when
        authentication is disabled.
    """
    raw = os.environ.get(API_KEY_ENV_VAR, "")
    return tuple(key for key in (part.strip() for part in raw.split(",")) if key)


def is_auth_enabled() -> bool:
    """
    Check whether API key authentication is active.

    Returns:
        True if at least one API key is configured.
    """
    return bool(get_api_keys())


def _matches_any(candidate: str, api_keys: tuple[str, ...]) -> bool:
    """
    Compare a candidate key against all configured keys in constant time.

    The comparison runs on bytes: secrets.compare_digest raises TypeError for a
    str holding a character above U+007F, and a header may carry such a byte.
    Starlette decodes header bytes as latin-1, so encoding back to latin-1
    restores the bytes the client sent, and it cannot fail for such a value.

    Every key is checked without an early exit, so the comparison time does not
    depend on which key matches.

    Args:
        candidate: Key presented by the client.
        api_keys: Configured keys.

    Returns:
        True if the candidate matches one of the configured keys.
    """
    presented = candidate.encode("latin-1", errors="replace")
    matched = False
    for api_key in api_keys:
        if secrets.compare_digest(presented, api_key.encode()):
            matched = True
    return matched


async def require_api_key(
    request: Request,
    header_key: Annotated[str | None, Depends(_api_key_header)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    """
    Reject the request when API key authentication fails.

    The dependency is a no-op while authentication is disabled, which keeps the
    previous behavior for deployments without API_KEY.

    Args:
        request: Incoming request, used for the rejection log only.
        header_key: Value of the X-API-Key header, if present.
        bearer: Credentials from the Authorization header, if present.

    Raises:
        HTTPException: 401 when the key is missing or invalid.
    """
    api_keys = get_api_keys()
    if not api_keys:
        return

    # Both schemes are advertised as alternatives, so either credential admits
    # the request. A stale header next to a valid bearer token must not reject.
    presented = [candidate for candidate in (header_key, bearer.credentials if bearer else None) if candidate]
    matched = False
    for candidate in presented:
        if _matches_any(candidate, api_keys):
            matched = True
    if matched:
        return

    # Never log the presented value, only the reason and the target path.
    logger.warning("Rejected unauthenticated request to %s: %s", request.url.path, "invalid API key" if presented else "missing API key")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_UNAUTHORIZED_MESSAGE,
        headers={"WWW-Authenticate": "Bearer"},
    )
