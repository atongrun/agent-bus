"""Event routes: create, stream (SSE), acknowledge."""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from server.auth import verify_token
from server.db import (
    ack_event,
    check_new_events,
    get_event,
    get_max_event_id,
    get_pending_events,
    insert_event,
    mark_delivered,
)
from server.models import AckResponse, EventCreate, EventResponse

router = APIRouter(prefix="/events", tags=["events"])


def _row_to_response(row: dict) -> dict:
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
    }


@router.post("", status_code=201)
async def create_event(
    event: EventCreate,
    request: Request,
    _: bool = Depends(verify_token),
):
    """Create a new event. Returns the created event with server-assigned fields."""
    payload_json = json.dumps(event.payload, ensure_ascii=False)
    row = insert_event(
        from_agent=event.from_agent,
        to_agent=event.to_agent,
        event_type=event.type,
        payload_json=payload_json,
    )
    return _row_to_response(row)


@router.post("/{event_id}/ack")
async def acknowledge_event(
    event_id: int,
    request: Request,
    _: bool = Depends(verify_token),
):
    """Acknowledge an event, marking it as processed."""
    # Check if event exists
    row = get_event(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # Already acked — idempotent, return success
    if row["status"] == "acked":
        return {
            "id": event_id,
            "status": "acked",
            "acked_at": row["acked_at"],
        }

    success = ack_event(event_id)
    if not success:
        raise HTTPException(status_code=409, detail="Event cannot be acked (already acked or failed)")

    updated = get_event(event_id)
    return {
        "id": event_id,
        "status": "acked",
        "acked_at": updated["acked_at"] if updated else None,
    }


@router.get("/stream")
async def stream_events(
    request: Request,
    agent: str = Query(..., min_length=1, description="Agent name to receive events for"),
    _: bool = Depends(verify_token),
):
    """SSE endpoint that streams events to an agent.

    On connect, replays all un-acked events (pending/delivered).
    Then polls for new events every 500ms.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        # Phase 1: Replay all pending/delivered (un-acked) events
        pending = get_pending_events(agent)
        for row in pending:
            # Mark as delivered if still pending
            if row["status"] == "pending":
                mark_delivered(row["id"])
                row["status"] = "delivered"
            data = _row_to_response(row)
            yield f"id: {row['id']}\nevent: message\ndata: {json.dumps(data)}\n\n"

        # Phase 2: Initialize last_id to the highest event ID this agent has,
        # so polling doesn't replay already-seen events (including acked ones)
        last_id = max(
            get_max_event_id(agent),
            max((r["id"] for r in pending), default=0)
        )

        # Phase 3: Poll for new events
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            new_events = check_new_events(agent, last_id)
            for row in new_events:
                last_id = max(last_id, row["id"])
                if row["status"] == "pending":
                    mark_delivered(row["id"])
                    row["status"] = "delivered"
                data = _row_to_response(row)
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
