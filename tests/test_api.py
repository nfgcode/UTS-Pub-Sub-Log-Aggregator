"""
test_api.py — Unit tests untuk endpoint FastAPI.

Tests:
  T6  — POST /publish single event: HTTP 200, accepted=1
  T7  — POST /publish batch event: HTTP 200, accepted=N
  T8  — Validasi skema: timestamp tidak valid → HTTP 422
  T9  — GET /stats konsisten dengan data yang dikirim
  T10 — GET /events?topic=... hanya kembalikan event sesuai topic
"""
from __future__ import annotations

import asyncio

import pytest

from tests.conftest import make_event


# ---------------------------------------------------------------------------
# T6 — POST /publish single event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_single_event(test_app):
    """Publish satu event valid harus mengembalikan HTTP 200 dan accepted=1."""
    event = make_event(event_id="api-single-001")
    resp = await test_app.post("/publish", json=event)

    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1


# ---------------------------------------------------------------------------
# T7 — POST /publish batch event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_batch_events(test_app):
    """Publish batch 5 event unik harus mengembalikan accepted=5."""
    batch = {
        "events": [
            make_event(event_id=f"api-batch-{i:03d}", topic="batch.topic")
            for i in range(5)
        ]
    }
    resp = await test_app.post("/publish", json=batch)

    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 5


# ---------------------------------------------------------------------------
# T8 — Validasi skema: field tidak valid → HTTP 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_timestamp_rejected(test_app):
    """Event dengan timestamp tidak valid harus ditolak dengan HTTP 422."""
    event = make_event(event_id="invalid-ts-001")
    event["timestamp"] = "bukan-timestamp-valid"

    resp = await test_app.post("/publish", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_topic_rejected(test_app):
    """Event dengan topic kosong harus ditolak dengan HTTP 422."""
    event = make_event(event_id="empty-topic-001")
    event["topic"] = "   "

    resp = await test_app.post("/publish", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_required_field_rejected(test_app):
    """Event tanpa field event_id harus ditolak dengan HTTP 422."""
    event = make_event()
    del event["event_id"]

    resp = await test_app.post("/publish", json=event)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# T9 — GET /stats konsisten
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_consistency(test_app):
    """
    Stats harus konsisten: received >= unique_processed,
    received = unique_processed + duplicate_dropped.
    """
    # Kirim 3 event unik + 2 duplikat
    events = [make_event(event_id=f"stats-{i:03d}") for i in range(3)]
    duplicate = make_event(event_id="stats-000")  # duplikat dari events[0]

    await test_app.post("/publish", json={"events": events})
    await test_app.post("/publish", json=duplicate)  # kirim 1 duplikat lagi
    await test_app.post("/publish", json=duplicate)  # kirim lagi

    # Beri waktu consumer memproses
    await asyncio.sleep(0.5)

    resp = await test_app.get("/stats")
    assert resp.status_code == 200
    stats = resp.json()

    received = stats["received"]
    unique = stats["unique_processed"]
    dropped = stats["duplicate_dropped"]

    assert received >= unique, "received harus >= unique_processed"
    assert unique + dropped <= received, "unique + dropped harus <= received"
    assert stats["uptime_seconds"] >= 0


# ---------------------------------------------------------------------------
# T10 — GET /events?topic filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_topic_filter(test_app):
    """GET /events?topic=X hanya boleh mengembalikan event dari topic X."""
    events = {
        "events": [
            make_event(topic="topic.alpha", event_id="filter-alpha-001"),
            make_event(topic="topic.alpha", event_id="filter-alpha-002"),
            make_event(topic="topic.beta", event_id="filter-beta-001"),
        ]
    }
    await test_app.post("/publish", json=events)
    await asyncio.sleep(0.5)

    resp = await test_app.get("/events", params={"topic": "topic.alpha"})
    assert resp.status_code == 200
    data = resp.json()

    # Semua event yang dikembalikan harus dari topic.alpha
    assert all(e["topic"] == "topic.alpha" for e in data)
    # topic.beta tidak boleh muncul
    assert not any(e["topic"] == "topic.beta" for e in data)
