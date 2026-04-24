"""
test_dedup.py — Unit tests untuk logika deduplication.

Tests:
  T1 — Event baru berhasil diproses (try_process_event returns True)
  T2 — Event duplikat ditolak (try_process_event returns False)
  T3 — Persistensi dedup store: instance baru membaca DB yang sama
  T4 — Composite key: event_id sama tapi topic berbeda = BUKAN duplikat
  T5 — Concurrent duplicates: hanya satu yang lolos meski dikirim bersamaan
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from tests.conftest import make_event


# ---------------------------------------------------------------------------
# T1 — Event baru berhasil diproses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_event_processed(dedup_store):
    """Event yang belum pernah diterima harus berhasil diproses."""
    event = make_event(event_id="unique-evt-001")
    result = await dedup_store.try_process_event(event)
    assert result is True, "Event baru seharusnya diproses (True)"


# ---------------------------------------------------------------------------
# T2 — Event duplikat ditolak
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_event_rejected(dedup_store):
    """Event yang sama (topic + event_id) hanya diproses sekali."""
    event = make_event(event_id="dup-evt-001")

    first = await dedup_store.try_process_event(event)
    second = await dedup_store.try_process_event(event)
    third = await dedup_store.try_process_event(event)  # kirim 3x

    assert first is True, "Pertama harus lolos"
    assert second is False, "Kedua harus ditolak (duplikat)"
    assert third is False, "Ketiga harus ditolak (duplikat)"


# ---------------------------------------------------------------------------
# T3 — Persistensi dedup store setelah 'restart'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_persists_across_instances(tmp_db: Path):
    """
    Simulasi restart: DedupStore instance kedua membaca database yang sama
    dan harus menolak event yang sudah diproses oleh instance pertama.
    """
    from src.dedup_store import DedupStore

    # Instance pertama — proses event
    store1 = DedupStore(db_path=tmp_db)
    await store1.initialize()
    event = make_event(event_id="persist-evt-001")
    result1 = await store1.try_process_event(event)
    assert result1 is True

    # Instance kedua — simulasi 'setelah restart'
    store2 = DedupStore(db_path=tmp_db)
    await store2.initialize()
    result2 = await store2.try_process_event(event)
    assert result2 is False, (
        "Setelah 'restart', event yang sama harus tetap ditolak "
        "karena dedup store persisten di SQLite"
    )


# ---------------------------------------------------------------------------
# T4 — Composite key: topic berbeda = bukan duplikat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_event_id_different_topic_not_duplicate(dedup_store):
    """event_id sama tetapi topic berbeda BUKAN duplikat."""
    event_id = "shared-event-id"
    event_a = make_event(topic="topic.alpha", event_id=event_id)
    event_b = make_event(topic="topic.beta", event_id=event_id)

    result_a = await dedup_store.try_process_event(event_a)
    result_b = await dedup_store.try_process_event(event_b)

    assert result_a is True, "topic.alpha harus lolos"
    assert result_b is True, "topic.beta dengan event_id sama harus LOLOS (bukan duplikat)"


# ---------------------------------------------------------------------------
# T5 — Concurrent duplicates: hanya satu yang berhasil
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_duplicate_only_one_processed(dedup_store):
    """
    Simulasi at-least-once: 10 goroutine mengirim event yang sama secara
    bersamaan. Hanya satu yang boleh berhasil diproses.
    """
    event = make_event(event_id="concurrent-evt-001")
    n = 10

    results = await asyncio.gather(
        *[dedup_store.try_process_event(event) for _ in range(n)]
    )

    successes = sum(1 for r in results if r is True)
    assert successes == 1, (
        f"Hanya 1 dari {n} concurrent request yang boleh berhasil, "
        f"tapi got {successes}"
    )
