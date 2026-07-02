"""Pydantic models for request/response validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    """Request body for creating a new event."""
    from_agent: str = Field(..., alias="from_agent", min_length=1, max_length=128)
    to_agent: str = Field(..., alias="to_agent", min_length=1, max_length=128)
    type: str = Field(..., min_length=1, max_length=128)
    payload: dict = Field(default_factory=dict)


class EventResponse(BaseModel):
    """Full event object returned in responses."""
    id: int
    from_agent: str
    to_agent: str
    type: str
    payload: dict
    status: str
    created_at: str
    delivered_at: Optional[str] = None
    acked_at: Optional[str] = None
    retry_count: int = 0


class AckResponse(BaseModel):
    """Response after acknowledging an event."""
    id: int
    status: str
    acked_at: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
