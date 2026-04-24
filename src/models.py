"""
models.py — Pydantic models untuk validasi skema Event.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, field_validator


class EventModel(BaseModel):
    """Model event tunggal dengan validasi skema."""

    topic: str
    event_id: str
    timestamp: str  # ISO 8601
    source: str
    payload: Dict[str, Any] = {}

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("topic tidak boleh kosong")
        return v.strip()

    @field_validator("event_id")
    @classmethod
    def event_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_id tidak boleh kosong")
        return v.strip()

    @field_validator("source")
    @classmethod
    def source_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source tidak boleh kosong")
        return v.strip()

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_iso8601(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("timestamp harus dalam format ISO 8601")
        return v


class BatchPublishRequest(BaseModel):
    """Request body untuk batch publish."""

    events: List[EventModel]


class PublishResponse(BaseModel):
    accepted: int
    message: str


class ProcessedEvent(BaseModel):
    topic: str
    event_id: str
    timestamp: str
    source: str
    payload: Dict[str, Any]
    processed_at: str


class StatsResponse(BaseModel):
    received: int
    unique_processed: int
    duplicate_dropped: int
    topics: List[str]
    uptime_seconds: float
    queue_size: int
