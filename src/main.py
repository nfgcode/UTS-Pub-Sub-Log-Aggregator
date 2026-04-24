"""
main.py — FastAPI Pub-Sub Log Aggregator.

Endpoint:
  POST /publish          — terima single / batch event; validasi skema
  GET  /events?topic=... — kembalikan event unik yang telah diproses
  GET  /stats            — received, unique_processed, duplicate_dropped,
                           topics, uptime, queue_size
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.consumer import EventConsumer
from src.dedup_store import DedupStore
from src.models import (
    BatchPublishRequest,
    EventModel,
    ProcessedEvent,
    PublishResponse,
    StatsResponse,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("aggregator")

# ---------------------------------------------------------------------------
# Lifespan — startup & shutdown
# ---------------------------------------------------------------------------

QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", "10000"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inisialisasi resources saat startup; bersihkan saat shutdown."""
    db_path = Path(os.getenv("DEDUP_DB_PATH", "/app/data/dedup.db"))

    logger.info("=== Aggregator starting up | DB: %s ===", db_path)

    store = DedupStore(db_path=db_path)
    await store.initialize()

    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    consumer = EventConsumer(queue=queue, dedup_store=store)
    consumer.start()

    # Simpan di app.state agar dapat diakses dari endpoint
    app.state.dedup_store = store
    app.state.event_queue = queue
    app.state.consumer = consumer
    app.state.start_time = time.monotonic()

    logger.info("Aggregator siap menerima event pada port 8080")
    yield

    logger.info("=== Aggregator shutting down ===")
    await consumer.stop()
    logger.info("Shutdown selesai")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pub-Sub Log Aggregator",
    description=(
        "Layanan aggregator berbasis Pub-Sub dengan idempotent consumer "
        "dan persistent deduplication store (SQLite)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _event_to_dict(event: EventModel) -> Dict[str, Any]:
    return {
        "topic": event.topic,
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "source": event.source,
        "payload": event.payload,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/publish",
    response_model=PublishResponse,
    summary="Publish single atau batch event",
)
async def publish(
    body: Union[EventModel, BatchPublishRequest],
) -> PublishResponse:
    """
    Terima satu event atau batch event dalam satu request.

    - Single: `{ "topic": ..., "event_id": ..., ... }`
    - Batch:  `{ "events": [ { ... }, { ... } ] }`

    Validasi skema dilakukan oleh Pydantic sebelum event masuk ke queue.
    Event kemudian diproses secara async oleh background consumer.
    """
    store: DedupStore = app.state.dedup_store
    queue: asyncio.Queue = app.state.event_queue

    if isinstance(body, EventModel):
        events = [body]
    else:
        events = body.events

    if not events:
        raise HTTPException(status_code=400, detail="Tidak ada event dalam request")

    # Increment received counter (persisten di SQLite)
    await store.increment_received(len(events))

    queued = 0
    for event in events:
        try:
            queue.put_nowait(_event_to_dict(event))
            queued += 1
        except asyncio.QueueFull:
            logger.warning(
                "Queue penuh — event topic=%s event_id=%s dibuang",
                event.topic, event.event_id,
            )

    logger.info("Diterima %d event(s), masuk queue: %d", len(events), queued)

    return PublishResponse(
        accepted=len(events),
        message=f"{queued} event masuk queue; {len(events) - queued} dibuang (queue penuh)",
    )


@app.get(
    "/events",
    response_model=List[ProcessedEvent],
    summary="Daftar event unik yang telah diproses",
)
async def get_events(
    topic: Optional[str] = Query(default=None, description="Filter berdasarkan topic"),
) -> List[ProcessedEvent]:
    """
    Kembalikan daftar event yang telah berhasil diproses (unik).
    Opsional filter by `topic`.
    """
    store: DedupStore = app.state.dedup_store
    events = await store.get_events(topic=topic)
    return [ProcessedEvent(**e) for e in events]


@app.get(
    "/stats",
    response_model=StatsResponse,
    summary="Statistik sistem",
)
async def get_stats() -> StatsResponse:
    """
    Kembalikan statistik operasional:
    - `received`          : total event diterima (termasuk duplikat)
    - `unique_processed`  : event unik yang berhasil diproses
    - `duplicate_dropped` : event yang terdeteksi sebagai duplikat
    - `topics`            : daftar topic aktif
    - `uptime_seconds`    : waktu hidup layanan sejak startup
    - `queue_size`        : jumlah event yang masih mengantre
    """
    store: DedupStore = app.state.dedup_store
    queue: asyncio.Queue = app.state.event_queue
    start_time: float = app.state.start_time

    db_stats = await store.get_stats()
    uptime = time.monotonic() - start_time

    return StatsResponse(
        received=db_stats["received"],
        unique_processed=db_stats["unique_processed"],
        duplicate_dropped=db_stats["duplicate_dropped"],
        topics=db_stats["topics"],
        uptime_seconds=round(uptime, 2),
        queue_size=queue.qsize(),
    )


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        log_level="info",
    )
