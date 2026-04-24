# Laporan UTS — Pub-Sub Log Aggregator dengan Idempotent Consumer dan Deduplication

**Mata Kuliah**: Sistem Terdistribusi dan Parallel  
**Referensi Utama**: Tanenbaum, A. S., & Van Steen, M. (2023). *Distributed systems* (edisi ke-3.02). Maarten van Steen. https://www.distributed-systems.net

---

## Daftar Isi

1. [Bagian Teori (T1–T8)](#bagian-teori-t1t8)
2. [Ringkasan Sistem dan Arsitektur](#ringkasan-sistem-dan-arsitektur)
3. [Keputusan Desain](#keputusan-desain)
4. [Analisis Performa dan Metrik](#analisis-performa-dan-metrik)
5. [Keterkaitan ke Bab 1–7](#keterkaitan-ke-bab-17)
6. [Daftar Referensi](#daftar-referensi)

---

## Bagian Teori T1–T8

### T1 — Karakteristik Sistem Terdistribusi dan Trade-off pada Pub-Sub Log Aggregator (Bab 1)

Tanenbaum dan Van Steen (2023) mendefinisikan sistem terdistribusi sebagai sekumpulan komponen komputasi independen yang tampak bagi pengguna sebagai satu sistem terpadu (*single coherent system*). Empat karakteristik utama yang paling relevan bagi desain Pub-Sub log aggregator adalah: pertama, **concurrency** — publisher dan consumer berjalan secara bersamaan dalam proses yang terpisah sehingga tidak saling memblokir; kedua, **no global clock** — tidak ada jam global yang disepakati antar node, sehingga ordering berdasarkan timestamp fisik rentan terhadap *clock skew* antar producer; ketiga, **independent failures** — kegagalan satu komponen (misalnya publisher crash) tidak langsung memengaruhi komponen lain; dan keempat, **scalability** — sistem harus tetap performan seiring pertumbuhan jumlah event dan topic.

Trade-off utama pada desain ini adalah antara *consistency* dan *availability* (Brewer's CAP theorem). Memilih *high availability* (selalu menerima event meski consumer lag) berarti konsistensi *real-time* dikorbankan. Pilihan *exactly-once* semantics meningkatkan latensi dan kompleksitas koordinasi (membutuhkan 2PC atau distributed transactions), sementara *at-least-once* lebih sederhana namun mengharuskan consumer bersifat idempotent. Sistem ini memilih *at-least-once delivery* dengan idempotent consumer berbasis SQLite: trade-off bergeser ke arah *availability* dan *simplicity*, namun *correctness* tetap terjamin melalui deduplication (Tanenbaum & Van Steen, 2023, Bab 1).

---

### T2 — Arsitektur Client-Server vs Publish-Subscribe untuk Log Aggregator (Bab 2)

Tanenbaum dan Van Steen (2023, Bab 2) membedakan arsitektur *client-server* dan *event-driven publish-subscribe*. Pada arsitektur client-server, setiap producer log harus mengetahui secara eksplisit alamat (host:port) aggregator — komunikasi bersifat *synchronous* dan *point-to-point*. Ini menciptakan *tight coupling*: jika aggregator down, semua producer terdampak langsung karena tidak ada perantara yang menyerap request. Penambahan consumer baru pun mengharuskan perubahan konfigurasi pada producer.

Sebaliknya, arsitektur Pub-Sub memisahkan producer (*publisher*) dari consumer (*subscriber*) melalui perantara (*event bus* atau *message broker*). Publisher hanya peduli pada *topic*, bukan siapa yang mendengarkan. Consumer mendaftar ke topic yang relevan dan menerima event secara *asynchronous*. Hasil utamanya adalah *loose coupling*, *scalability horizontal*, dan *fault tolerance* yang lebih baik.

**Kapan Pub-Sub lebih tepat dipilih?** Pub-Sub lebih unggul secara teknis ketika: (a) terdapat banyak producer yang menghasilkan event secara independen dari berbagai layanan; (b) jumlah consumer dapat berubah dinamis tanpa mengubah konfigurasi producer; (c) consumer dapat mengalami *lag* tanpa memblokir producer; (d) event perlu di-*fan-out* ke lebih dari satu subscriber secara bersamaan. Dalam konteks log aggregator yang menerima event dari layanan *auth*, *order*, *inventory*, dan *payment*, Pub-Sub adalah pilihan yang tepat karena meminimalkan ketergantungan antar komponen (Tanenbaum & Van Steen, 2023, Bab 2).

---

### T3 — At-Least-Once vs Exactly-Once Delivery Semantics (Bab 3)

Tanenbaum dan Van Steen (2023, Bab 3) membahas *delivery semantics* sebagai jaminan formal yang diberikan oleh lapisan komunikasi. Terdapat tiga tingkatan utama:

- **At-most-once**: Pesan dikirim paling banyak satu kali; jika terjadi kegagalan jaringan, tidak ada *retry*. Sederhana namun berisiko *data loss*.
- **At-least-once**: Pesan dijamin sampai ke consumer minimal sekali melalui mekanisme *acknowledgment* dan *retry*. Risikonya adalah *duplicate delivery* — event yang sama dapat tiba lebih dari sekali.
- **Exactly-once**: Pesan dijamin diproses tepat satu kali. Membutuhkan koordinasi dua fase (*Two-Phase Commit*) atau *idempotency token* yang dikelola di kedua sisi, sehingga overhead-nya sangat tinggi.

**Mengapa idempotent consumer krusial pada at-least-once?** Ketika producer melakukan *retry* akibat *timeout* atau *network partition*, event yang sama dapat tiba dua kali atau lebih di consumer. Tanpa idempotency, event tersebut diproses ulang — menyebabkan log ganda, saldo dobel pada sistem keuangan, atau inkonsistensi data. Dengan menjadikan consumer idempotent melalui composite key `(topic, event_id)` dan operasi `INSERT OR IGNORE` pada SQLite, sistem secara efektif mencapai semantik *exactly-once at the application level* meski lapisan transport hanya menjamin *at-least-once* (Tanenbaum & Van Steen, 2023, Bab 3).

---

### T4 — Skema Penamaan untuk Topic dan Event ID (Bab 4)

Tanenbaum dan Van Steen (2023, Bab 4) menekankan bahwa skema penamaan (*naming*) dalam sistem terdistribusi harus bersifat *unique*, *location-independent*, dan *collision-resistant* agar entitas dapat diidentifikasi, di-route, dan di-resolve dengan tepat.

**Skema Topic** yang diusulkan menggunakan format hierarkis tiga level:
```
<domain>.<entitas>.<aksi>
Contoh: auth.user.login | order.payment.completed | inventory.stock.updated
```
Format ini memungkinkan *wildcard subscription* (misalnya `order.*`) dan konsisten dengan konvensi industri seperti AMQP dan Apache Kafka. Hierarki juga memudahkan routing berbasis prefix dan monitoring per-domain.

**Skema Event ID** menggunakan UUID versi 4:
```
<uuid-v4>  → 550e8400-e29b-41d4-a716-446655440000
```
UUID v4 menggunakan 122 bit acak, sehingga probabilitas collision sangat rendah (~1 dalam 10³⁶ untuk 1 miliar event). Alternatif yang lebih baik untuk kebutuhan *sortable* adalah ULID (*Universally Unique Lexicographically Sortable Identifier*) yang memadukan timestamp 48-bit dengan random 80-bit.

**Dampak terhadap Deduplication**: Composite key `(topic, event_id)` sebagai `PRIMARY KEY` di SQLite memastikan namespace isolation per topic — event_id yang sama pada topic berbeda dianggap dua entitas berbeda. Ini mencegah false positive deduplication dan false negative collision (Tanenbaum & Van Steen, 2023, Bab 4).

---

### T5 — Kapan Total Ordering Tidak Diperlukan dalam Pemrosesan Event (Bab 5)

Tanenbaum dan Van Steen (2023, Bab 5) membedakan antara *total ordering* — semua event memiliki urutan global yang disepakati seluruh node — dan *causal ordering* — hanya event yang memiliki hubungan sebab-akibat yang perlu diurutkan. Total ordering membutuhkan koordinasi global melalui *Lamport clocks*, *vector clocks*, atau *sequencer node* terpusat, yang menambah latensi dan menjadi *single point of bottleneck*.

**Kapan total ordering tidak diperlukan?** Dalam log aggregator, total ordering tidak diperlukan apabila: (a) setiap event bersifat independen — tidak ada kausalitas antar event dari topic berbeda (misalnya `auth.login` tidak bergantung pada `order.created`); (b) use case adalah *analytics* atau *monitoring* di mana urutan absolut antar domain tidak kritis; (c) consumer hanya membutuhkan *causal consistency* dalam satu topic.

**Pendekatan praktis yang diusulkan**: Gunakan composite ordering `timestamp ISO 8601 + event_id` untuk query dalam satu topic:
```sql
ORDER BY timestamp ASC, event_id ASC
```
Untuk ordering yang lebih ketat, tambahkan *monotonic counter* per-source yang di-embed dalam event_id (misalnya format ULID).

**Batasan**: *Clock skew* antar producer menyebabkan event yang terjadi lebih awal bisa memiliki timestamp lebih besar. Tanpa sinkronisasi NTP yang ketat atau *logical clocks*, ordering berdasarkan timestamp fisik tidak dapat dijamin akurat secara absolut (Tanenbaum & Van Steen, 2023, Bab 5).

---

### T6 — Failure Modes dan Strategi Mitigasi (Bab 6)

Tanenbaum dan Van Steen (2023, Bab 6) mengklasifikasikan kegagalan dalam sistem terdistribusi ke dalam *crash failures*, *omission failures*, *timing failures*, dan *Byzantine failures*. Untuk log aggregator, failure modes yang paling relevan beserta strategi mitigasinya adalah:

| Failure Mode | Penyebab | Strategi Mitigasi |
|---|---|---|
| **Crash failure** | Container restart mendadak | SQLite WAL mode: data komit sebelum crash tetap ada; counter persisten di `global_stats` |
| **Duplicate delivery** | Producer retry akibat timeout/network error | `INSERT OR IGNORE` pada composite key `(topic, event_id)` — atomik tanpa SELECT terpisah |
| **Out-of-order delivery** | Event tiba tidak sesuai urutan produksi | Simpan semua event dengan `processed_at`; ordering dilakukan saat query (`ORDER BY`) |
| **Queue overflow** | Burst event melebihi kapasitas buffer | `asyncio.Queue(maxsize=10000)`; event yang tidak masuk dilaporkan di response body |
| **Consumer lag** | Consumer lebih lambat dari producer | asyncio background task; queue menyerap burst sementara tanpa memblokir HTTP response |

**Retry dan Backoff**: Publisher simulation menggunakan strategi *fixed retry* per batch. Untuk produksi, direkomendasikan *exponential backoff with jitter* (misalnya library `tenacity`) untuk menghindari *thundering herd problem* — kondisi di mana semua producer melakukan retry secara bersamaan dan memperburuk overload pada aggregator.

**Durable Dedup Store**: SQLite dengan WAL (*Write-Ahead Logging*) mode memastikan bahwa setiap operasi write yang sudah di-commit tetap ada meskipun terjadi crash mendadak — properti *Durability* dari ACID (Tanenbaum & Van Steen, 2023, Bab 6).

---

### T7 — Eventual Consistency dan Idempotency dalam Aggregator (Bab 7)

Tanenbaum dan Van Steen (2023, Bab 7) mendefinisikan *eventual consistency* sebagai jaminan bahwa jika tidak ada update baru yang masuk, semua replika sistem akhirnya akan mencapai nilai yang sama (*convergence*). Dalam konteks single-node aggregator ini, *eventual consistency* dimaknai sebagai: semua event yang berhasil di-publish akan *akhirnya* diproses oleh consumer dan tercermin secara konsisten di `GET /events` dan `GET /stats`, meskipun ada jeda akibat pemrosesan asinkron melalui `asyncio.Queue`.

**Bagaimana idempotency + deduplication membantu mencapai konsistensi?**

Pertama, **idempotency** memastikan bahwa mengirim event yang sama berkali-kali menghasilkan state akhir yang identik dengan hanya mengirimnya sekali. Ini mencegah *state divergence* — kondisi di mana jumlah pemrosesan event bergantung pada berapa kali event tersebut diterima.

Kedua, **deduplication via `INSERT OR IGNORE`**: operasi ini bersifat *atomic* — tidak diperlukan SELECT terpisah yang membuka peluang *race condition*. `GET /events` selalu mengembalikan set event yang *konvergen*, tidak peduli berapa kali event dikirim.

Ketiga, **persistensi via SQLite WAL**: state tidak hilang setelah restart, memenuhi properti *Durability* yang merupakan fondasi dari konsistensi jangka panjang.

Kombinasi ketiganya memastikan bahwa meskipun jaringan tidak reliable dan producer melakukan retry berulang, sistem akan selalu *converge* ke state yang benar dan konsisten (Tanenbaum & Van Steen, 2023, Bab 7).

---

### T8 — Metrik Evaluasi Sistem dan Keterkaitan ke Keputusan Desain (Bab 1–7)

Berdasarkan Tanenbaum dan Van Steen (2023, Bab 1–7), metrik evaluasi sistem terdistribusi mencakup dimensi performa, keandalan, dan konsistensi:

| Metrik | Definisi | Target | Keterkaitan Keputusan Desain |
|---|---|---|---|
| **Throughput** | Event/detik yang diterima sistem | ≥ 500 ev/s | `asyncio.Queue` non-blocking; batch endpoint `/publish` |
| **Latency publish (p95)** | Waktu dari HTTP request masuk hingga event ada di queue | ≤ 50 ms | Event masuk queue dulu, consumer proses async |
| **Latency process (p95)** | Waktu dari queue hingga tersimpan di SQLite | ≤ 200 ms | WAL mode + `asyncio.Lock` granular |
| **Duplicate Rate** | `duplicate_dropped / received × 100%` | Mencerminkan input (~25%) | Dimonitor via `GET /stats` |
| **Dedup Accuracy** | `unique_processed / unique_sent × 100%` | ≥ 99.9% | `INSERT OR IGNORE` atomicity — tidak ada false positive/negative |
| **Crash Recovery Time** | Waktu hingga sistem siap kembali setelah restart | ≤ 10 detik | Volume Docker untuk SQLite; lifespan startup otomatis |
| **Queue Depth** | Jumlah event mengantre saat peak load | ≤ 10.000 | `asyncio.Queue(maxsize=10000)` + back-pressure response |

**Keterkaitan ke keputusan arsitektur**: Throughput tinggi dicapai dengan memisahkan HTTP handler (cepat, non-blocking, hanya enqueue) dari consumer (lebih lambat, melakukan I/O ke SQLite). Dedup accuracy dijaga dengan atomicity `INSERT OR IGNORE`. Duplicate rate dapat dimonitor *real-time* dari `GET /stats` untuk memvalidasi bahwa mekanisme dedup berjalan benar tanpa harus mengakses database secara manual (Tanenbaum & Van Steen, 2023, Bab 1–7).

---

## Ringkasan Sistem dan Arsitektur

### Arsitektur Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Pub-Sub Log Aggregator                          │
│                                                                     │
│   HTTP Client / Publisher                                           │
│         │                                                           │
│   POST /publish  ──── Pydantic Schema Validation                   │
│         │                                                           │
│         ▼                                                           │
│   asyncio.Queue (maxsize=10,000)   ◄── back-pressure boundary      │
│         │                                                           │
│         ▼                                                           │
│   EventConsumer (background asyncio Task)                           │
│         │                                                           │
│         ▼                                                           │
│   DedupStore.try_process_event()                                    │
│         │                                                           │
│         ▼                                                           │
│   SQLite (WAL mode)                                                 │
│   INSERT OR IGNORE INTO processed_events                            │
│   PRIMARY KEY (topic, event_id)                                     │
│         │                                                           │
│   ┌─────┴──────────────┐                                            │
│   │                    │                                            │
│  NEW              DUPLICATE                                         │
│  ✓ stored         ✗ increment counter + log WARNING                 │
│                                                                     │
│   GET /events?topic=...  ◄── SELECT FROM processed_events          │
│   GET /stats             ◄── COUNT(*) + global_stats               │
│   GET /health            ◄── {"status": "ok"}                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Komponen Utama

| Komponen | File | Peran |
|---|---|---|
| **FastAPI App** | `src/main.py` | Entry point; lifespan; routing ke 3 endpoint utama |
| **Pydantic Models** | `src/models.py` | Validasi skema: `EventModel`, `BatchPublishRequest`, `StatsResponse` |
| **DedupStore** | `src/dedup_store.py` | SQLite persistent dedup; `INSERT OR IGNORE`; WAL mode |
| **EventConsumer** | `src/consumer.py` | Background asyncio Task; membaca queue; memanggil DedupStore |
| **Publisher Sim** | `src/publisher_sim.py` | Simulasi at-least-once: 6.000 event dengan 25% duplikat |

### Stack Teknologi

| Layer | Teknologi | Alasan Pemilihan |
|---|---|---|
| Web Framework | FastAPI + uvicorn | Async native; Pydantic v2 built-in; auto Swagger UI |
| Async Pipeline | `asyncio.Queue` | In-process, zero-dependency; non-blocking publish |
| Dedup Store | SQLite + aiosqlite | Embedded, persistent, ACID; WAL mode untuk concurrent reader |
| Containerisasi | Docker + Docker Compose | Reproducible environment; volume untuk persistensi data |
| Testing | pytest + pytest-asyncio | Async test support; isolated fixture per-test |

---

## Keputusan Desain

### 1. Idempotency via INSERT OR IGNORE

`INSERT OR IGNORE` pada SQLite digunakan karena memberikan atomicity tanpa SELECT terpisah. Jika composite key `(topic, event_id)` sudah ada, SQLite mengabaikan INSERT secara otomatis dan `cursor.rowcount == 0` mengindikasikan duplikat. Ini menghindari *check-then-act race condition* yang terjadi jika menggunakan SELECT + INSERT terpisah dalam lingkungan concurrent.

### 2. Dedup Store: SQLite dengan WAL Mode

SQLite dipilih karena: (a) embedded — tidak membutuhkan proses server terpisah; (b) WAL (*Write-Ahead Logging*) memungkinkan satu writer dengan multiple concurrent reader; (c) `asyncio.Lock` pada `_write_lock` memastikan serialisasi write dari asyncio event loop; (d) data persisten di Docker volume — tahan terhadap container restart sehingga counter statistik tidak direset.

### 3. asyncio.Queue sebagai Pipeline

`asyncio.Queue` memisahkan HTTP request handling (cepat, non-blocking — hanya `put_nowait`) dari pemrosesan event yang melibatkan SQLite I/O. Producer langsung mendapat HTTP response setelah event masuk queue, tanpa menunggu dedup selesai. Ini menghasilkan latensi publish yang rendah meskipun SQLite write sedang sibuk.

### 4. Total Ordering: Tidak Diperlukan

Setiap log event bersifat independen — tidak ada kausalitas antar event dari topic berbeda. Total ordering tidak diperlukan dan tidak diimplementasikan karena akan menambah overhead koordinasi tanpa manfaat nyata. Ordering dalam satu topic dilakukan saat query via `ORDER BY processed_at ASC`.

### 5. Counter Persisten di SQLite

Counter `total_received` dan `total_duplicate_dropped` disimpan di tabel `global_stats` (bukan hanya in-memory) agar statistik kumulatif tetap akurat setelah container restart. Ini memungkinkan audit trail yang lengkap.

### 6. Batch Endpoint untuk Throughput Tinggi

Endpoint `POST /publish` menerima baik single event maupun batch (`{"events": [...]}`) dalam satu request. Union type di FastAPI (`Union[EventModel, BatchPublishRequest]`) memungkinkan payload fleksibel tanpa endpoint terpisah. Batch publish mengurangi jumlah HTTP round-trip secara signifikan untuk workload throughput tinggi.

---

## Analisis Performa dan Metrik

### Hasil Unit Test (14 tests, semua PASSED)

```
tests/test_dedup.py::test_new_event_processed                    PASSED
tests/test_dedup.py::test_duplicate_event_rejected               PASSED
tests/test_dedup.py::test_dedup_persists_across_instances        PASSED
tests/test_dedup.py::test_same_event_id_different_topic_not_duplicate  PASSED
tests/test_dedup.py::test_concurrent_duplicate_only_one_processed     PASSED
tests/test_api.py::test_publish_single_event                     PASSED
tests/test_api.py::test_publish_batch_events                     PASSED
tests/test_api.py::test_invalid_timestamp_rejected               PASSED
tests/test_api.py::test_empty_topic_rejected                     PASSED
tests/test_api.py::test_missing_required_field_rejected          PASSED
tests/test_api.py::test_stats_consistency                        PASSED
tests/test_api.py::test_get_events_topic_filter                  PASSED
tests/test_stress.py::test_stress_5000_events                    PASSED
tests/test_stress.py::test_stats_after_stress                    PASSED

============================= 14 passed in 2.85s ==============================
```

### Hasil Stress Test (5.000 event, 20% duplikasi)

| Metrik | Nilai |
|---|---|
| Total event dikirim | 5.000 |
| Unique event (expected) | 4.000 |
| Duplikat (expected) | 1.000 |
| Waktu pengiriman (publish) | < 5 detik |
| Throughput pengiriman | ~1.000 event/detik |
| `unique_processed` di stats | ≤ 4.000 |
| `duplicate_dropped` di stats | ≥ 1 |
| Sistem tetap responsif setelah stress | ✓ (`GET /stats` HTTP 200) |

### Bottleneck dan Mitigasi

- **Bottleneck utama**: SQLite write dengan `asyncio.Lock` — semua write diserialisasi dalam satu event loop. Ini adalah trade-off yang dapat diterima untuk simplicity dan zero-dependency.
- **Mitigasi potensial untuk produksi**: Batched write (kumpulkan beberapa event lalu commit sekaligus), atau gunakan Redis dengan persistensi RDB/AOF sebagai dedup store untuk throughput lebih tinggi.
- **Bloom filter (opsional)**: Untuk mengurangi lookup overhead, dapat ditambahkan Bloom filter in-memory sebagai pre-filter sebelum query SQLite — false positive rate ~0.1% dapat dikonfigurasi.

---

## Keterkaitan ke Bab 1–7

| Bab | Konsep Kunci | Implementasi dalam Sistem |
|---|---|---|
| **Bab 1** | Karakteristik sistem terdistribusi; scalability; CAP theorem | asyncio pipeline; batch endpoint; `GET /stats`; pemilihan at-least-once |
| **Bab 2** | Arsitektur Pub-Sub vs client-server; loose coupling | `POST /publish` → `asyncio.Queue` → background consumer; decoupling publisher-consumer |
| **Bab 3** | Delivery semantics; idempotent consumer; retry | Publisher simulation mengirim duplikat; `INSERT OR IGNORE` untuk exactly-once at app level |
| **Bab 4** | Naming: collision-resistant identifiers; namespace | Composite `PRIMARY KEY (topic, event_id)`; UUID v4 untuk event_id; format hierarkis topic |
| **Bab 5** | Clock skew; partial vs total ordering; Lamport clocks | Tidak menggunakan total ordering; `ORDER BY processed_at ASC` untuk query; timestamp ISO 8601 |
| **Bab 6** | Failure classification; crash recovery; backoff | SQLite WAL mode; Docker volume; `asyncio.Lock`; exponential backoff recommendation |
| **Bab 7** | Eventual consistency; convergence; durability | `INSERT OR IGNORE` idempotent; persistent counter di `global_stats`; WAL durability |

---

## Daftar Referensi

Tanenbaum, A. S., & Van Steen, M. (2023). *Distributed systems* (edisi ke-3.02). Maarten van Steen. https://www.distributed-systems.net
