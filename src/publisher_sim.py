"""
publisher_sim.py — Simulasi at-least-once delivery.

Script ini mengirim >5.000 event ke aggregator dengan ≥20% duplikasi,
mensimulasikan kondisi at-least-once delivery yang terjadi pada
distributed system ketika producer melakukan retry setelah timeout/error.

Usage (local):
    python -m src.publisher_sim --url http://localhost:8080 --total 6000 --dup-rate 0.25

Usage (Docker Compose):
    AGGREGATOR_URL=http://aggregator:8080 python -m src.publisher_sim
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("publisher_sim")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

AGGREGATOR_URL = os.getenv("AGGREGATOR_URL", "http://localhost:8080")
TOPICS = ["auth.login", "auth.logout", "order.created", "order.paid",
          "inventory.updated", "user.signup", "payment.failed", "session.expired"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(topic: str, event_id: str, source: str = "publisher-sim") -> Dict[str, Any]:
    return {
        "topic": topic,
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "payload": {
            "sim": True,
            "rand": random.randint(1, 9999),
        },
    }


def build_event_batch(total: int, dup_rate: float) -> List[Dict[str, Any]]:
    """
    Bangun daftar event dengan ≥dup_rate duplikasi.

    Strategi:
    - Buat `unique_count` event unik terlebih dahulu.
    - Sisanya diambil secara acak dari event unik (duplikasi).
    """
    unique_count = int(total * (1 - dup_rate))
    dup_count = total - unique_count

    unique_events: List[Dict[str, Any]] = []
    for _ in range(unique_count):
        topic = random.choice(TOPICS)
        event_id = str(uuid.uuid4())
        unique_events.append(_make_event(topic, event_id))

    duplicates: List[Dict[str, Any]] = []
    for _ in range(dup_count):
        base = random.choice(unique_events)
        # Duplikasi: event_id dan topic sama, timestamp bisa berbeda
        dup = _make_event(base["topic"], base["event_id"])
        duplicates.append(dup)

    all_events = unique_events + duplicates
    random.shuffle(all_events)
    return all_events


# ---------------------------------------------------------------------------
# Async sender
# ---------------------------------------------------------------------------

async def wait_for_aggregator(url: str, retries: int = 30) -> None:
    """Tunggu hingga aggregator siap (health check)."""
    async with httpx.AsyncClient(timeout=5) as client:
        for i in range(retries):
            try:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    logger.info("Aggregator siap di %s", url)
                    return
            except Exception:
                pass
            logger.info("Menunggu aggregator... (%d/%d)", i + 1, retries)
            await asyncio.sleep(2)
    raise RuntimeError(f"Aggregator tidak dapat dijangkau di {url}")


async def send_batch(
    client: httpx.AsyncClient,
    url: str,
    events: List[Dict[str, Any]],
    batch_size: int = 100,
) -> Dict[str, int]:
    """Kirim event dalam batch, kembalikan ringkasan."""
    total_accepted = 0
    failed = 0

    for i in range(0, len(events), batch_size):
        chunk = events[i: i + batch_size]
        body = {"events": chunk}
        try:
            resp = await client.post(f"{url}/publish", json=body, timeout=30)
            if resp.status_code == 200:
                total_accepted += resp.json().get("accepted", 0)
            else:
                logger.warning("Batch gagal: HTTP %d", resp.status_code)
                failed += len(chunk)
        except Exception as exc:
            logger.error("Error saat kirim batch: %s", exc)
            failed += len(chunk)

        if (i // batch_size) % 10 == 0:
            logger.info("Progress: %d/%d event terkirim", i + len(chunk), len(events))

    return {"accepted": total_accepted, "failed": failed}


async def main(url: str, total: int, dup_rate: float) -> None:
    logger.info("=== Publisher Simulation ===")
    logger.info("Target: %s | Total: %d | Dup rate: %.0f%%", url, total, dup_rate * 100)

    await wait_for_aggregator(url)

    events = build_event_batch(total, dup_rate)
    unique_expected = int(total * (1 - dup_rate))
    dup_expected = total - unique_expected
    logger.info(
        "Event disiapkan: %d total (%d unik + %d duplikat)",
        len(events), unique_expected, dup_expected,
    )

    t0 = time.perf_counter()
    async with httpx.AsyncClient() as client:
        result = await send_batch(client, url, events)
    elapsed = time.perf_counter() - t0

    logger.info("=== Hasil Pengiriman ===")
    logger.info("Total dikirim  : %d", total)
    logger.info("Accepted       : %d", result["accepted"])
    logger.info("Failed         : %d", result["failed"])
    logger.info("Waktu          : %.2f detik", elapsed)
    logger.info("Throughput     : %.0f event/detik", total / elapsed)

    # Ambil stats dari aggregator
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{url}/stats")
        if resp.status_code == 200:
            stats = resp.json()
            logger.info("=== Stats Aggregator ===")
            logger.info("received         : %d", stats.get("received"))
            logger.info("unique_processed : %d", stats.get("unique_processed"))
            logger.info("duplicate_dropped: %d", stats.get("duplicate_dropped"))
            logger.info("topics           : %s", stats.get("topics"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pub-Sub Publisher Simulation")
    parser.add_argument("--url", default=AGGREGATOR_URL)
    parser.add_argument("--total", type=int, default=6000)
    parser.add_argument("--dup-rate", type=float, default=0.25)
    args = parser.parse_args()

    asyncio.run(main(url=args.url, total=args.total, dup_rate=args.dup_rate))
