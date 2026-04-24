"""
test_stress.py — Stress test dan performa minimum.

Tests:
  T11 — Proses 5.000 event (≥20% duplikat) dalam waktu wajar
  T12 — Statistik akhir konsisten dengan jumlah yang dikirim
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime, timezone

import pytest

from tests.conftest import make_event


def build_stress_events(total: int = 5000, dup_rate: float = 0.20):
    """Buat list event dengan jumlah duplikat sesuai dup_rate."""
    unique_count = int(total * (1 - dup_rate))
    unique_events = [
        make_event(
            topic=random.choice(["stress.alpha", "stress.beta", "stress.gamma"]),
            event_id=str(uuid.uuid4()),
        )
        for _ in range(unique_count)
    ]
    duplicates = [
        make_event(
            topic=e["topic"],
            event_id=e["event_id"],
        )
        for e in random.choices(unique_events, k=total - unique_count)
    ]
    all_events = unique_events + duplicates
    random.shuffle(all_events)
    return all_events, unique_count


@pytest.mark.asyncio
async def test_stress_5000_events(test_app):
    """
    Sistem harus mampu menerima 5.000 event (≥20% duplikat) dalam ≤60 detik
    dan tetap responsif.
    """
    TOTAL = 5000
    DUP_RATE = 0.20
    BATCH_SIZE = 200
    TIME_LIMIT_SECONDS = 60.0

    events, unique_count = build_stress_events(TOTAL, DUP_RATE)
    dup_count = TOTAL - unique_count

    t0 = time.perf_counter()

    # Kirim dalam batch
    for i in range(0, len(events), BATCH_SIZE):
        chunk = events[i: i + BATCH_SIZE]
        resp = await test_app.post("/publish", json={"events": chunk})
        assert resp.status_code == 200, f"Batch ke-{i // BATCH_SIZE} gagal"

    elapsed = time.perf_counter() - t0

    assert elapsed < TIME_LIMIT_SECONDS, (
        f"Pengiriman 5.000 event seharusnya selesai dalam {TIME_LIMIT_SECONDS}s, "
        f"tapi membutuhkan {elapsed:.2f}s"
    )

    # Tunggu consumer memproses semua event
    await asyncio.sleep(min(elapsed * 0.5, 5.0))

    # Verifikasi sistem masih responsif
    resp = await test_app.get("/stats")
    assert resp.status_code == 200, "GET /stats harus tetap responsif setelah stress test"

    stats = resp.json()
    assert stats["received"] >= TOTAL, (
        f"received ({stats['received']}) harus >= {TOTAL}"
    )

    # Unique processed tidak boleh melebihi jumlah unique yang dikirim
    assert stats["unique_processed"] <= unique_count + 10, (  # toleransi kecil
        f"unique_processed ({stats['unique_processed']}) melebihi "
        f"unique yang dikirim ({unique_count})"
    )

    throughput = TOTAL / elapsed
    print(f"\n[Stress] Throughput: {throughput:.0f} event/detik, elapsed: {elapsed:.2f}s")
    print(f"[Stress] unique_expected={unique_count}, dup_expected={dup_count}")
    print(f"[Stress] received={stats['received']}, unique_processed={stats['unique_processed']}, "
          f"duplicate_dropped={stats['duplicate_dropped']}")


@pytest.mark.asyncio
async def test_stats_after_stress(test_app):
    """
    Stats setelah pengiriman harus mencerminkan duplikasi:
    duplicate_dropped > 0 jika ada duplikat yang dikirim.
    """
    # Kirim 10 event dengan 1 duplikat
    base = make_event(event_id="stress-stats-dup")
    events = [make_event(event_id=f"stress-stats-{i:03d}") for i in range(9)]
    events.append(base)   # 9 unik + 1 pertama
    events.append(base)   # + 1 duplikat

    await test_app.post("/publish", json={"events": events})
    await asyncio.sleep(0.5)

    resp = await test_app.get("/stats")
    assert resp.status_code == 200
    stats = resp.json()

    assert stats["duplicate_dropped"] >= 1, (
        "Harus ada minimal 1 duplikat yang tercatat di stats"
    )
