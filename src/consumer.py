"""
consumer.py — Background asyncio consumer untuk Pub-Sub pipeline.

Consumer membaca event dari asyncio.Queue, memeriksa DedupStore,
dan memproses hanya event yang belum pernah diterima sebelumnya.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from src.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class EventConsumer:
    """
    Background consumer yang membaca dari asyncio.Queue dan melakukan
    deduplication berdasarkan composite key (topic, event_id).

    Arsitektur pipeline:
      Publisher → asyncio.Queue → EventConsumer → DedupStore (SQLite)
    """

    def __init__(self, queue: asyncio.Queue, dedup_store: "DedupStore") -> None:
        self._queue = queue
        self._dedup_store = dedup_store
        self._task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Mulai background consumer task."""
        self._running = True
        self._task = asyncio.create_task(self._run(), name="event-consumer")
        logger.info("EventConsumer dimulai")

    async def stop(self) -> None:
        """Hentikan consumer secara graceful — tunggu queue kosong."""
        self._running = False
        if self._task:
            # Kirim sentinel agar loop keluar
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            logger.info("EventConsumer dihentikan")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Loop utama consumer — berjalan hingga sentinel (None) diterima."""
        logger.info("EventConsumer: mulai memproses queue")
        while self._running:
            try:
                event: Dict[str, Any] | None = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            # Sentinel untuk graceful shutdown
            if event is None:
                self._queue.task_done()
                break

            await self._process_event(event)
            self._queue.task_done()

    async def _process_event(self, event: Dict[str, Any]) -> None:
        """
        Proses satu event:
          1. Coba INSERT ke DedupStore (INSERT OR IGNORE).
          2. Jika berhasil → event baru, log sebagai processed.
          3. Jika gagal   → duplikat, log eksplisit dan buang.
        """
        topic = event.get("topic", "unknown")
        event_id = event.get("event_id", "unknown")

        try:
            is_new = await self._dedup_store.try_process_event(event)
        except Exception as exc:
            logger.error(
                "Gagal memproses event topic=%s event_id=%s: %s",
                topic, event_id, exc,
            )
            return

        if is_new:
            logger.info(
                "PROCESSED | topic=%-20s | event_id=%s",
                topic, event_id,
            )
        else:
            logger.warning(
                "DUPLICATE DETECTED | topic=%-20s | event_id=%s — diabaikan",
                topic, event_id,
            )
