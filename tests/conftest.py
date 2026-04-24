"""
conftest.py — Shared pytest fixtures.

Menggunakan LifespanManager (anyio) atau httpx dengan lifespan=True
untuk memastikan app.state terinisialisasi pada saat test berjalan.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def tmp_db(tmp_path: Path) -> Path:
    """Path ke database SQLite sementara (per-test, terisolasi)."""
    return tmp_path / "test.db"


@pytest_asyncio.fixture
async def dedup_store(tmp_db: Path):
    """Instance DedupStore dengan DB sementara, sudah terinisialisasi."""
    from src.dedup_store import DedupStore
    store = DedupStore(db_path=tmp_db)
    await store.initialize()
    return store


@pytest_asyncio.fixture
async def test_app(tmp_db: Path):
    """
    FastAPI test client dengan lifespan yang berjalan penuh.

    Strategi: set env var DEDUP_DB_PATH SEBELUM app module diimpor,
    kemudian gunakan httpx AsyncClient dengan app=app dan menjalankan
    lifespan secara eksplisit melalui ASGITransport.

    Karena httpx tidak trigger lifespan, kita jalankan startup/shutdown
    secara manual menggunakan starlette TestClient approach via anyio.
    """
    os.environ["DEDUP_DB_PATH"] = str(tmp_db)

    # Import app setelah env var diset
    from src.main import app, lifespan

    # Jalankan lifespan context manager secara manual
    async with lifespan(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client


def make_event(
    topic: str = "test.topic",
    event_id: str = "evt-001",
    source: str = "pytest",
    timestamp: str = "2026-04-24T10:00:00+00:00",
    payload: dict | None = None,
) -> dict:
    """Helper: buat dict event valid."""
    return {
        "topic": topic,
        "event_id": event_id,
        "timestamp": timestamp,
        "source": source,
        "payload": payload or {"test": True},
    }
