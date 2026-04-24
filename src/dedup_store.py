"""
dedup_store.py — Persistent deduplication store berbasis SQLite.

Menggunakan composite PRIMARY KEY (topic, event_id) + INSERT OR IGNORE
untuk menjamin atomicity dan idempotency pada setiap write operation.
WAL mode diaktifkan untuk performa concurrent access yang lebih baik.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(os.getenv("DEDUP_DB_PATH", "/app/data/dedup.db"))


class DedupStore:
    """
    Persistent dedup store dengan SQLite embedded.

    Schema:
      processed_events — menyimpan event yang sudah diproses,
                         PRIMARY KEY (topic, event_id) mencegah duplikat.
      global_stats     — menyimpan counter persisten (received, dropped).
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Inisialisasi
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Buat tabel dan inisialisasi counter bila belum ada."""
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS processed_events (
                    topic        TEXT NOT NULL,
                    event_id     TEXT NOT NULL,
                    timestamp    TEXT NOT NULL,
                    source       TEXT NOT NULL,
                    payload      TEXT NOT NULL DEFAULT '{}',
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (topic, event_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS global_stats (
                    key   TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Pastikan baris counter ada
            await db.executemany(
                "INSERT OR IGNORE INTO global_stats (key, value) VALUES (?, 0)",
                [("total_received",), ("total_duplicate_dropped",)],
            )

            await db.commit()
        logger.info("DedupStore diinisialisasi: %s", self.db_path)

    # ------------------------------------------------------------------
    # Core — try_process_event
    # ------------------------------------------------------------------

    async def try_process_event(self, event: Dict[str, Any]) -> bool:
        """
        Coba simpan event secara atomik menggunakan INSERT OR IGNORE.

        Returns:
            True  — event baru, berhasil diproses.
            False — duplikat, event diabaikan.

        INSERT OR IGNORE memanfaatkan constraint PRIMARY KEY (topic, event_id):
        jika key sudah ada, baris tidak dimasukkan dan rowcount = 0.
        Ini memberikan atomicity tanpa memerlukan SELECT terlebih dahulu.
        """
        async with self._write_lock:
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute("PRAGMA journal_mode=WAL")

                processed_at = datetime.now(timezone.utc).isoformat()
                cur = await db.execute(
                    """
                    INSERT OR IGNORE INTO processed_events
                        (topic, event_id, timestamp, source, payload, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["topic"],
                        event["event_id"],
                        event["timestamp"],
                        event["source"],
                        json.dumps(event.get("payload", {})),
                        processed_at,
                    ),
                )

                is_new = cur.rowcount > 0

                # Update counter persisten
                if is_new:
                    pass  # received sudah di-increment di endpoint
                else:
                    await db.execute(
                        "UPDATE global_stats SET value = value + 1"
                        " WHERE key = 'total_duplicate_dropped'"
                    )

                await db.commit()
                return is_new

    async def increment_received(self, count: int = 1) -> None:
        """Tambah counter total_received (dipanggil di endpoint /publish)."""
        async with self._write_lock:
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute(
                    "UPDATE global_stats SET value = value + ? WHERE key = 'total_received'",
                    (count,),
                )
                await db.commit()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_events(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        """Kembalikan daftar event unik, opsional filter by topic."""
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            if topic:
                cur = await db.execute(
                    """SELECT topic, event_id, timestamp, source, payload, processed_at
                       FROM processed_events WHERE topic = ?
                       ORDER BY processed_at ASC""",
                    (topic,),
                )
            else:
                cur = await db.execute(
                    """SELECT topic, event_id, timestamp, source, payload, processed_at
                       FROM processed_events ORDER BY processed_at ASC"""
                )
            rows = await cur.fetchall()

        return [
            {
                "topic": r["topic"],
                "event_id": r["event_id"],
                "timestamp": r["timestamp"],
                "source": r["source"],
                "payload": json.loads(r["payload"]),
                "processed_at": r["processed_at"],
            }
            for r in rows
        ]

    async def get_stats(self) -> Dict[str, Any]:
        """Kembalikan statistik agregat dari database."""
        async with aiosqlite.connect(str(self.db_path)) as db:
            cur = await db.execute("SELECT COUNT(*) FROM processed_events")
            unique_processed = (await cur.fetchone())[0]

            cur = await db.execute(
                "SELECT DISTINCT topic FROM processed_events ORDER BY topic"
            )
            topics = [r[0] for r in await cur.fetchall()]

            cur = await db.execute("SELECT key, value FROM global_stats")
            counters: Dict[str, int] = {r[0]: r[1] for r in await cur.fetchall()}

        return {
            "received": counters.get("total_received", 0),
            "unique_processed": unique_processed,
            "duplicate_dropped": counters.get("total_duplicate_dropped", 0),
            "topics": topics,
        }
