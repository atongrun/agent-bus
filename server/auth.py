"""Token-based authentication for Agent Bus API."""

import os

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)


def get_token() -> str:
    """Get the configured server token."""
    return os.environ.get("AGENT_BUS_TOKEN", "dev-token")


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> bool:
    """Verify the bearer token from the request.

    Checks Authorization header first. If not present, also checks
    for token in query parameter (useful for SSE EventSource which
    doesn't support custom headers).
    """
    token = get_token()

    # Check Authorization header
    if credentials and credentials.credentials == token:
        return True

    # Check query parameter (for SSE connections)
    if "token" in request.query_params:
        if request.query_params["token"] == token:
            return True

    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
