"""Strictly read-only operator cockpit routes."""

import secrets
from functools import lru_cache
from importlib import resources
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from server.auth import verify_operator
from server.db import get_event_status_counts, get_operator_events
from server.events import row_to_event_response

router = APIRouter(prefix="/operator", tags=["operator"])
EventStatus = Literal["pending", "delivered", "acked", "failed"]


@lru_cache(maxsize=1)
def _cockpit_template() -> str:
    return (
        resources.files("server").joinpath("cockpit.html").read_text(encoding="utf-8")
    )


def _security_headers(*, nonce: str | None = None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": (
            "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if nonce is not None:
        headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}'; "
            f"style-src 'nonce-{nonce}'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "base-uri 'none'; "
            "form-action 'none'; "
            "frame-ancestors 'none'"
        )
    return headers


def _reject_cross_site_fetch(request: Request) -> None:
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(
            status_code=403, detail="Cross-site requests are not allowed"
        )


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def cockpit(_: None = Depends(verify_operator)) -> HTMLResponse:
    """Serve the single-file cockpit shell."""
    nonce = secrets.token_urlsafe(18)
    html = _cockpit_template().replace("__CSP_NONCE__", nonce)
    return HTMLResponse(html, headers=_security_headers(nonce=nonce))


@router.get("/api/events")
async def list_operator_events(
    request: Request,
    response: Response,
    status: EventStatus | None = None,
    q: str | None = Query(default=None, max_length=200),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    _: None = Depends(verify_operator),
) -> dict:
    """Return a read-only, newest-first event page across all identities."""
    _reject_cross_site_fetch(request)
    response.headers.update(_security_headers())
    rows, has_more = get_operator_events(
        status=status,
        query=q.strip() if q and q.strip() else None,
        before_id=before_id,
        limit=limit,
    )
    items = [row_to_event_response(row) for row in rows]
    return {
        "items": items,
        "counts": get_event_status_counts(),
        "has_more": has_more,
        "next_before_id": items[-1]["id"] if has_more and items else None,
    }
