"""Event routes: create, stream (SSE), acknowledge."""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from server.auth import AuthContext, verify_token
from server.db import (
    ack_event,
    check_new_events,
    get_event,
    get_failed_events,
    get_max_event_id,
    get_pending_events,
    insert_event,
    mark_delivered,
    record_failure,
    requeue_event,
)
from server.models import EventCreate, EventFail

router = APIRouter(prefix="/events", tags=["events"])


def row_to_event_response(row: dict) -> dict:
    """Convert a database row dict to an API response dict."""
    return {
        "id": row["id"],
        "from_agent": row["from_agent"],
        "to_agent": row["to_agent"],
        "type": row["type"],
        "payload": json.loads(row["payload_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
        "acked_at": row["acked_at"],
        "retry_count": row["retry_count"],
        "last_error": row["last_error"],
    }


def _require_agent(auth: AuthContext, agent: str, action: str) -> None:
    """Enforce per-agent token scope while preserving legacy shared-token mode."""
    if auth.legacy:
        return
    if auth.agent != agent:
        raise HTTPException(
            status_code=403, detail=f"Token is not allowed to {action} for this agent"
        )


@router.post("", status_code=201)
async def create_event(
    event: EventCreate,
    request: Request,
    auth: AuthContext = Depends(verify_token),
):
    """Create a new event. Returns the created event with server-assigned fields."""
    _require_agent(auth, event.from_agent, "send events")
    payload_json = json.dumps(event.payload, ensure_ascii=False)
    row = insert_event(
        from_agent=event.from_agent,
        to_agent=event.to_agent,
        event_type=event.type,
        payload_json=payload_json,
    )
    return row_to_event_response(row)


@router.post("/{event_id}/ack")
async def acknowledge_event(
    event_id: int,
    request: Request,
    expected_retry_count: int | None = Query(default=None, ge=0),
    auth: AuthContext = Depends(verify_token),
):
    """Acknowledge an event, marking it as processed."""
    # Check if event exists
    row = get_event(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    _require_agent(auth, row["to_agent"], "ack events")

    outcome, updated = ack_event(event_id, expected_retry_count)
    if outcome == "conflict":
        raise HTTPException(
            status_code=409, detail="Failed events must be requeued before ACK"
        )
    if outcome == "stale":
        raise HTTPException(
            status_code=409,
            detail="Event attempt changed before ACK; inspect the current event state",
        )
    if updated is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return {
        "id": event_id,
        "status": "acked",
        "acked_at": updated["acked_at"],
    }


@router.post("/{event_id}/fail")
async def fail_event(
    event_id: int,
    body: EventFail,
    request: Request,
    auth: AuthContext = Depends(verify_token),
):
    """Record one failed handler attempt and apply the terminal threshold."""
    row = get_event(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    _require_agent(auth, row["to_agent"], "fail events")

    outcome, updated = record_failure(
        event_id,
        body.error,
        body.max_attempts,
        body.expected_retry_count,
    )
    if outcome == "conflict":
        raise HTTPException(
            status_code=409, detail="ACKed events cannot record failures"
        )
    if updated is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return {
        "id": event_id,
        "status": updated["status"],
        "retry_count": updated["retry_count"],
        "last_error": updated["last_error"],
        "attempt_recorded": outcome in ("recorded", "failed"),
    }


@router.get("/pending")
async def list_pending_events(
    request: Request,
    agent: str = Query(..., min_length=1, description="Agent name to inspect"),
    auth: AuthContext = Depends(verify_token),
):
    """List un-acked events for an agent without opening an SSE stream."""
    _require_agent(auth, agent, "list pending events")
    return [row_to_event_response(row) for row in get_pending_events(agent)]


@router.get("/failed")
async def list_failed_events(
    request: Request,
    agent: str = Query(..., min_length=1, description="Agent name to inspect"),
    auth: AuthContext = Depends(verify_token),
):
    """List terminally failed events for an agent."""
    _require_agent(auth, agent, "list failed events")
    return [row_to_event_response(row) for row in get_failed_events(agent)]


@router.post("/{event_id}/requeue")
async def requeue_failed_event(
    event_id: int,
    request: Request,
    auth: AuthContext = Depends(verify_token),
):
    """Explicitly return a recipient's terminal failed event to pending."""
    row = get_event(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_agent(auth, row["to_agent"], "requeue events")

    outcome, updated = requeue_event(event_id)
    if outcome == "conflict":
        raise HTTPException(
            status_code=409,
            detail="Only failed or already-pending events can be requeued",
        )
    if updated is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return row_to_event_response(updated)


@router.get("/stream")
async def stream_events(
    request: Request,
    agent: str = Query(
        ..., min_length=1, description="Agent name to receive events for"
    ),
    auth: AuthContext = Depends(verify_token),
):
    """SSE endpoint that streams events to an agent.

    On connect, replays all un-acked events (pending/delivered).
    Then polls for new events every 500ms.
    """
    _require_agent(auth, agent, "stream events")

    async def event_generator() -> AsyncGenerator[str, None]:
        # Capture the high-water mark before replay. An event created after this
        # point is either included in the replay query or has a larger ID for the
        # polling phase, so there is no query/max race that can skip it.
        last_id = get_max_event_id(agent)

        # Phase 1: Replay all pending/delivered (un-acked) events
        pending = get_pending_events(agent)
        for row in pending:
            row = mark_delivered(row["id"])
            if row is None or row["status"] not in ("pending", "delivered"):
                continue
            data = row_to_event_response(row)
            yield f"id: {row['id']}\nevent: message\ndata: {json.dumps(data)}\n\n"

        # Phase 2: advance past every replayed event without skipping events
        # created between the high-water read and the replay query.
        last_id = max(last_id, max((r["id"] for r in pending), default=0))

        # Phase 3: Poll for new events
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            new_events = check_new_events(agent, last_id)
            for row in new_events:
                last_id = max(last_id, row["id"])
                row = mark_delivered(row["id"])
                if row is None or row["status"] not in ("pending", "delivered"):
                    continue
                data = row_to_event_response(row)
                yield f"id: {row['id']}\nevent: message\ndata: {json.dumps(data)}\n\n"

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
