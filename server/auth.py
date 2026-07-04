"""Token-based authentication for Agent Bus API."""

import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller information.

    In legacy mode the shared token is accepted and no single agent identity is
    known. In agent-token mode the token maps to exactly one agent.
    """

    agent: str | None
    legacy: bool


def get_legacy_token() -> str:
    """Get the configured legacy shared token."""
    return os.environ.get("AGENT_BUS_TOKEN", "dev-token")


def get_agent_tokens() -> dict[str, str]:
    """Parse AGENT_BUS_AGENT_TOKENS as agent=token pairs."""
    raw = os.environ.get("AGENT_BUS_AGENT_TOKENS", "").strip()
    if not raw:
        return {}

    tokens: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise HTTPException(
                status_code=500,
                detail="Invalid AGENT_BUS_AGENT_TOKENS entry; expected agent=token",
            )
        agent, token = item.split("=", 1)
        agent = agent.strip()
        token = token.strip()
        if not agent or not token:
            raise HTTPException(
                status_code=500,
                detail="Invalid AGENT_BUS_AGENT_TOKENS entry; agent and token are required",
            )
        tokens[agent] = token
    return tokens


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Read bearer token from Authorization header or token query parameter."""
    if credentials:
        return credentials.credentials
    return request.query_params.get("token")


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AuthContext:
    """Verify the bearer token from the request.

    Checks Authorization header first. If not present, also checks
    for token in query parameter (useful for SSE EventSource which
    doesn't support custom headers).
    """
    presented = _extract_token(request, credentials)
    if not presented:
        raise HTTPException(status_code=401, detail="Invalid or missing authentication token")

    agent_tokens = get_agent_tokens()
    if agent_tokens:
        for agent, token in agent_tokens.items():
            if secrets.compare_digest(presented, token):
                return AuthContext(agent=agent, legacy=False)
        raise HTTPException(status_code=401, detail="Invalid or missing authentication token")

    if secrets.compare_digest(presented, get_legacy_token()):
        return AuthContext(agent=None, legacy=True)

    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
