# Pub-Sub Log Aggregator — UTS Sistem Terdistribusi dan Parallel

Layanan log aggregator berbasis **Pub-Sub pattern** dengan idempotent consumer
dan persistent deduplication store (SQLite + WAL mode). Dibangun menggunakan
**FastAPI** + **asyncio** + **aiosqlite**.

# LINK YOUTUBE: https://youtu.be/WEVxui9QDN0
# LINK DOKUMEN LAPORAN: https://drive.google.com/file/d/1mkshDhfQf1FVUYcrjSMtOCLoGDU_qzzW/view?usp=sharing
---

## Arsitektur Singkat

```
Publisher (HTTP)
      │
      ▼
POST /publish ──► asyncio.Queue (maxsize=10,000) ──► EventConsumer (background task)
                                                            │
                                                      DedupStore (SQLite WAL)
                                                      INSERT OR IGNORE
                                                      PRIMARY KEY (topic, event_id)
                                                            │
                                                  ┌─────────┴──────────┐
                                               BARU               DUPLIKAT
                                           (simpan DB)       (log WARNING + drop)
```

---

## Prasyarat

- **Docker** ≥ 24.0
- **Docker Compose** ≥ 2.x (opsional, untuk bonus +10%)
- Python 3.11+ (untuk local run dan testing)

---

## Build & Run

### Docker (Wajib)

```bash
# Build image
docker build -t uts-aggregator .

# Run container
docker run -p 8080:8080 -v aggregator_data:/app/data uts-aggregator
```

Buka browser: http://localhost:8080/docs (Swagger UI)

### Docker Compose (Bonus — publisher + aggregator terpisah)

```bash
# Build dan jalankan semua service
docker compose up --build

# Lihat log publisher
docker compose logs -f publisher

# Lihat log aggregator
docker compose logs -f aggregator

# Hentikan semua service
docker compose down
```

### Local (tanpa Docker)

```bash
pip install -r requirements.txt

# Windows PowerShell:
$env:DEDUP_DB_PATH = ".\data\dedup.db"
New-Item -ItemType Directory -Force -Path .\data
python -m src.main

# Linux/macOS:
DEDUP_DB_PATH=./data/dedup.db python -m src.main
```

---

## Daftar Endpoint API

| Method | Path | Deskripsi |
|--------|------|-----------|
| `POST` | `/publish` | Publish single atau batch event (validasi skema Pydantic) |
| `GET` | `/events` | Daftar event unik yang diproses; filter opsional `?topic=...` |
| `GET` | `/stats` | Statistik: received, unique_processed, duplicate_dropped, topics, uptime |
| `GET` | `/health` | Health check untuk Docker (`{"status": "ok"}`) |
| `GET` | `/docs` | Swagger UI interaktif |

### Contoh Request

**Single event:**
```bash
curl -X POST http://localhost:8080/publish \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "order.created",
    "event_id": "evt-abc-123",
    "timestamp": "2026-04-25T00:00:00+00:00",
    "source": "order-service",
    "payload": {"order_id": 42}
  }'
```

**Batch event (simulasi at-least-once — duplikat event_id):**
```bash
curl -X POST http://localhost:8080/publish \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {"topic": "auth.login", "event_id": "e-001", "timestamp": "2026-04-25T00:00:00+00:00", "source": "auth", "payload": {}},
      {"topic": "auth.login", "event_id": "e-001", "timestamp": "2026-04-25T00:00:01+00:00", "source": "auth", "payload": {}}
    ]
  }'
```

**Get stats:**
```bash
curl http://localhost:8080/stats
```

**Get events by topic:**
```bash
curl "http://localhost:8080/events?topic=order.created"
```

---

## Unit Tests (14 tests)

```bash
# Install dependencies
pip install -r requirements.txt

# Jalankan semua tests
pytest -v

# Jalankan stress test saja (verbose)
pytest tests/test_stress.py -v -s

# Jalankan dedup tests saja
pytest tests/test_dedup.py -v
```

**Cakupan test:**

| Test | File | Deskripsi |
|---|---|---|
| `test_new_event_processed` | test_dedup.py | Event baru → True |
| `test_duplicate_event_rejected` | test_dedup.py | Event duplikat → False (3x kirim) |
| `test_dedup_persists_across_instances` | test_dedup.py | Simulasi restart: instance baru tetap menolak event lama |
| `test_same_event_id_different_topic_not_duplicate` | test_dedup.py | event_id sama, topic beda = bukan duplikat |
| `test_concurrent_duplicate_only_one_processed` | test_dedup.py | 10 goroutine concurrent → hanya 1 berhasil |
| `test_publish_single_event` | test_api.py | POST /publish single → HTTP 200, accepted=1 |
| `test_publish_batch_events` | test_api.py | POST /publish batch 5 → HTTP 200, accepted=5 |
| `test_invalid_timestamp_rejected` | test_api.py | Timestamp tidak valid → HTTP 422 |
| `test_empty_topic_rejected` | test_api.py | Topic kosong → HTTP 422 |
| `test_missing_required_field_rejected` | test_api.py | Field wajib hilang → HTTP 422 |
| `test_stats_consistency` | test_api.py | received ≥ unique + dropped |
| `test_get_events_topic_filter` | test_api.py | Filter topic bekerja benar |
| `test_stress_5000_events` | test_stress.py | 5.000 event, 20% duplikat, < 60 detik |
| `test_stats_after_stress` | test_stress.py | duplicate_dropped ≥ 1 setelah stress |

---

## Simulasi At-Least-Once (Publisher)

```bash
# Local (aggregator harus sudah berjalan di port 8080)
python -m src.publisher_sim --url http://localhost:8080 --total 6000 --dup-rate 0.25

# Dalam Docker Compose (publisher berjalan otomatis setelah aggregator sehat)
docker compose up --build
```

---

## Struktur Repository

```
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI app (endpoints + lifespan)
│   ├── models.py            # Pydantic models (EventModel, BatchPublishRequest)
│   ├── dedup_store.py       # SQLite dedup store (WAL, INSERT OR IGNORE)
│   ├── consumer.py          # Background asyncio consumer
│   └── publisher_sim.py     # Publisher simulation (at-least-once)
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures (tmp DB, test app, make_event)
│   ├── test_dedup.py        # 5 tests: dedup logic + persistence
│   ├── test_api.py          # 7 tests: endpoint + schema validation + stats
│   └── test_stress.py       # 2 tests: 5.000 event + stats after stress
├── .dockerignore
├── .gitignore
├── Dockerfile               # python:3.11-slim, non-root user, port 8080
├── docker-compose.yml       # publisher + aggregator (bonus +10%)
├── pyproject.toml           # pytest configuration
├── requirements.txt         # Python dependencies
├── report.md                # Laporan desain + sitasi + teori T1-T8
└── README.md                # File ini
```

---

## Asumsi Desain

1. **Ordering**: Total ordering **tidak** diperlukan untuk log aggregator; setiap event bersifat independen antar topic.
2. **Dedup key**: Composite key `(topic, event_id)` — event_id yang sama pada topic berbeda dianggap dua event yang berbeda.
3. **Persistensi**: SQLite WAL mode di Docker volume — data tetap ada setelah container restart.
4. **Queue**: `asyncio.Queue` in-process; tidak menggunakan message broker eksternal (Kafka, RabbitMQ, dll).
5. **Counter**: `total_received` dan `total_duplicate_dropped` disimpan di SQLite agar tidak direset saat restart.
6. **Koneksi eksternal**: Tidak ada — semua komponen berjalan lokal di dalam container.

## Sitasi

Tanenbaum, A. S., & Van Steen, M. (2023). *Distributed systems* (edisi ke-3.02). Maarten van Steen. https://www.distributed-systems.net
