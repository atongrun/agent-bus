"""Bootstrap token exchange: low-privilege secret → high-privilege role token."""

import os
import secrets

from fastapi import APIRouter, Header, HTTPException

from server.auth import get_agent_tokens
from server.models import BootstrapTokenRequest

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])


@router.post("/token")
async def bootstrap_token(
    body: BootstrapTokenRequest,
    x_bootstrap_secret: str | None = Header(None),
) -> dict:
    """Exchange a valid bootstrap secret for an agent's role token.

    When AGENT_BUS_BOOTSTRAP_SECRET is unset the endpoint behaves as if it
    does not exist (404). This prevents leaking that the feature is available
    while still allowing machines to curl for their token when configured.
    """
    configured = os.environ.get("AGENT_BUS_BOOTSTRAP_SECRET", "").strip()
    if not configured:
        raise HTTPException(status_code=404, detail="Not Found")

    if x_bootstrap_secret is None:
        raise HTTPException(status_code=401, detail="Invalid bootstrap secret")

    if not secrets.compare_digest(x_bootstrap_secret, configured):
        raise HTTPException(status_code=401, detail="Invalid bootstrap secret")

    agent_tokens = get_agent_tokens()
    token = agent_tokens.get(body.agent)
    if token is None:
        raise HTTPException(status_code=404, detail="Not Found")

    return {"agent": body.agent, "token": token}
