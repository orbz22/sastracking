# Viral Trend Intelligence — Dev Plan (MVP)

> Modul pertama platform **SA SINC**. Dokumen bisnis lengkap: `../SA_SINC_Viral_Trend_Plan.pdf`.
> Fokus MVP: **1 platform (TikTok) × 1 vertikal (F&B Indonesia) × 1 USP (viral sekarang)**.
> Prinsip: **data dulu, dashboard belakangan.** Dikerjakan **nyicil** per milestone.

---

## 1. Tech Stack (default — bisa diganti)

| Lapis | Pilihan | Alasan |
|-------|---------|--------|
| Bahasa inti | **Python 3.11+** | Ekosistem scraping + data terbaik |
| Scraper | **Creative Center JSON** via `httpx` (utama) → Playwright (fallback) → Apify (darurat) | Sumber resmi TikTok, anti-bot ringan. Detail di §1b |
| Database | **SQLite** (MVP) → **PostgreSQL** (nanti) | Mulai tanpa server, migrasi saat scale |
| ORM | **SQLModel** (SQLAlchemy + Pydantic) | Model = schema, dipakai ulang di API |
| API | **FastAPI** + Uvicorn | Cepat, auto-docs, satu bahasa dgn scraper |
| Dashboard (MVP) | **FastAPI + Jinja2 + HTMX + Alpine.js** | Ship cepat, satu bahasa. Migrasi ke Next.js saat jual serius |
| Scheduler | **APScheduler** (MVP) → cron/Task Scheduler | Jalanin scrape harian |
| Config | `.env` via **pydantic-settings** | Rahasia & setting kepisah |

> **Kenapa bukan Next.js dari awal:** MVP butuh cepat kelihatan jalan. Satu bahasa (Python) = lebih ngebut. Dashboard "jualan" yang cakep dibangun setelah data + nilai kebukti.

---

## 1b. Strategi Akuisisi Data — DIREKOMENDASIKAN (hasil /deep-research)

Gerbang M1 = hidup-mati produk. Riset 2026: **jangan scrape app TikTok konsumen dulu** — anti-bot ML-nya blok single-IP dalam hitungan menit, butuh residential proxy + anti-deteksi (mahal, rapuh). Pakai pendekatan bertingkat:

| Tingkat | Sumber | Kapan | Catatan |
|---------|--------|-------|---------|
| **1 — UTAMA** | **TikTok Creative Center** (JSON internal via `httpx`) | MVP sekarang | GRATIS, resmi, filter negara (ID) + industri, 4 kategori (hashtag/sound/creator/video). Anti-bot ringan. Ref struktur endpoint: repo open-source `lofe-w/tiktok-creative-center-scraper-public` |
| **2 — fallback** | Creative Center via **Playwright** | Kalau muncul JS challenge | Render browser, mimik manusia |
| **3 — darurat** | **Apify actor** (Creative Center scraper) | Kalau self-scrape kena blok | Berbayar murah, offload anti-bot + risiko ToS ke pihak ketiga |
| **Fase 2 (nanti)** | Scrape app konsumen (Playwright + residential proxy) | Enrichment: engagement per-video, editing Level 2 | Butuh proxy, ditunda sampai MVP laku |

**JANGAN pakai:** TikTok Official Research API — akademik saja, larang komersil, cap 1.000 req/hari, approval ~4 minggu.

**Kenapa Creative Center nomor 1:** itu tool resmi TikTok yang justru DIBUAT buat marketer riset tren per negara + industri — persis kebutuhan produk. Legal jauh lebih aman (data publik agregat, bukan menyalin konten app), dan teknis paling ringan (bisa mulai `httpx` doang, tanpa Playwright/proxy).

> Sumber riset: [Scrapfly — How to Scrape TikTok 2026](https://scrapfly.io/blog/posts/how-to-scrape-tiktok-python-json) · [TikTok Creative Center Guide 2026](https://www.spocket.co/blogs/tiktok-creative-center-guide) · [lofe-w/tiktok-creative-center-scraper (GitHub)](https://github.com/lofe-w/tiktok-creative-center-scraper-public) · [Apify Creative Center Scraper](https://apify.com/doliz/tiktok-creative-center-scraper/api)

---

## 2. Struktur Folder (target)

```
viral-trend-mvp/
├── PLAN.md                  # dokumen ini
├── README.md               # cara jalanin
├── .env.example            # template config
├── .gitignore
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py           # load .env
│   ├── db.py               # koneksi + init DB
│   ├── models.py           # SQLModel: Trend, Snapshot, dll
│   ├── scrapers/
│   │   ├── base.py            # interface scraper (modular)
│   │   ├── creative_center.py # UTAMA: Creative Center via httpx
│   │   └── playwright_cc.py   # fallback kalau kena JS challenge
│   ├── metrics.py          # hitung velocity/volume/engagement + ambang "viral"
│   ├── editing.py          # deteksi gaya edit Level 1 (dari hashtag/sound)
│   ├── pipeline.py         # scrape → simpan → hitung metrik (1 run harian)
│   ├── api.py              # FastAPI: endpoint top-tren
│   └── web/
│       ├── templates/      # Jinja2 (dashboard)
│       └── static/
├── scripts/
│   └── run_once.py         # jalanin pipeline manual sekali
└── data/
    └── trends.db           # SQLite (gitignore)
```

---

## 3. Milestones (dicicil — centang kalau kelar)

### M0 — Setup proyek  ✅ SELESAI
- [x] `git init` + `.gitignore` (ignore `data/`, `.env`, `__pycache__`, `.venv`)
- [x] Virtualenv: **Python 3.12** (`py -3.12 -m venv .venv`) — catatan: butuh 3.10+ (sintaks `X | None`)
- [x] `requirements.txt` awal: `fastapi uvicorn sqlmodel httpx apscheduler pydantic-settings jinja2 python-dotenv`
- [ ] Playwright **opsional** (cuma kalau fallback dipakai): `pip install playwright && playwright install chromium`
- [x] `.env.example` + `app/config.py`
- **Done when:** `uvicorn app.api:app` nyala walau kosong. ✅ `/health`=200, DB `trends.db` kebentuk otomatis.

### M1 — Scraper spike: Creative Center  ✅ PROVEN + F&B filter
- [x] `scrapers/base.py`: interface `fetch_trends(...) -> list[dict]`
- [x] `scrapers/creative_center.py` + `scripts/run_once.py`: narik tren hashtag ID nyata (posts/views)
- [x] **Filter industri F&B** — via klik UI dropdown (`_select_industry`), parser tahan multi-tag industri
- [~] **Login** (persistent profile) — scaffold siap: `scripts/login.py` (login manual sekali) + `_load_more` (klik "View more"). **Butuh user login sekali** buat buka >3 baris.
- [ ] Tambah kategori: trending **sound** + **video** (halaman terpisah)
- **Status:** F&B data nyata tampil di dashboard (3 baris anon). Login → 20–100 baris.
- ⚠️ `headless=True` diblok → **headed**. Scraper pakai **persistent context** (`.pw-profile/`, gitignore).

**Cakupan tanpa login (hasil riset lanjutan):**
- Tanpa login, tiap kombinasi filter cuma kasih **~3 baris**. Solusi sah: **sapu banyak kombinasi**, bukan tembus login.
- `fetch_many()` menyapu **periode (7/30/90) × industri** (F&B + Health, News, Sports, Travel, Household) dalam **satu browser**.
- Hasil: **3 → 50 hashtag unik** (~17×), ~170 detik. Semua data publik.
- Jebakan yang sudah ditangani:
  - Views antar-period tidak sebanding (90h kumulatif) → `period` disimpan per snapshot, metrik hanya banding period sama.
  - Klik "View more" tanpa login memunculkan **modal login** yang memblokir dropdown → modal ditutup otomatis (Escape) lalu berhenti.
  - Setelah scroll, dropdown industri keluar viewport → `scroll_into_view` sebelum klik.
- Opsi berbayar tanpa login TikTok (kalau mau lepas dari scrape lokal): Apify `doliz` Creative Center, EnsembleData, TickerTrends.

**Temuan riset lapangan (penting):**
- Creative Center rebrand → **"TikTok One Creative Suite"**, URL tren: `ads.tiktok.com/creative/creativeCenter/trends/hashtag?region=ID&period=7`
- `httpx` langsung ke JSON API → **`40101 no permission`** (butuh signature JS). Buntu.
- Data **tidak** di HTML awal & **tidak** via XHR JSON → **dirender ke DOM** (SSR + hydrate).
- **Solusi: scrape DOM via Playwright** (parse innerText tabel). `headless=True` **DIBLOK** → wajib **headed**.
- Anon = **top 3**/kategori; login = lebih banyak.
- Konsekuensi: scheduler harian (M7) harus jalan **headed** (Task Scheduler di mesin, bukan headless server).

### M2 — Database + simpan harian  ✅ SELESAI
- [x] `models.py`: `Trend` (+ industry) + `Snapshot` (trend_id, tanggal, views, video_count, rank)
- [x] `db.py`: init SQLite + create tables
- [x] `pipeline.py`: scrape → upsert Trend → insert Snapshot harian (**idempoten** per hari)
- **Done when:** DB nyimpen histori (bukan overwrite). ✅ Diverifikasi: run 2x/hari = ga dobel; snapshot beda tanggal numpuk. **Histori = aset prediksi.**

### M3 — Metrik viral + definisi ambang  ✅ SELESAI (logika)
- [x] `metrics.py`: **velocity** (Δviews/hari), **growth_rate**, **rank_delta**, **views_per_post** (proxy)
- [x] Ambang "sedang viral" (`ViralThresholds`, kalibrasi kasar — sesuaikan nanti)
- [x] Flag status: **baru / naik / puncak / turun** + `is_viral`
- **Done when:** metrik keluar per trend. ✅ Diverifikasi: histori 2-hari → velocity 9.4M/hari, +18.8%/hari, status "naik", viral=True.
- ⏳ Catatan: **engagement true** (like/share) belum ada — butuh enrichment (fase 2). Akurasi velocity naik seiring data harian numpuk.

### M4 — API  ✅ SELESAI
- [x] `GET /trends?category=&region=&only_viral=&limit=` → top tren + metrik, **terurut viral → velocity → rank**
- [x] `GET /trends/{id}` → detail + histori snapshot
- **Done when:** endpoint balikin data asli dari DB. ✅ Diverifikasi via TestClient (sort benar, detail+histori, filter, 404).

### M5 — Dashboard minimal  ✅ SELESAI
- [x] Halaman `GET /` (Jinja): tabel top tren + rank/views/posts/velocity
- [x] Badge status (naik/puncak/turun) + pill **VIRAL**, stat kartu (dilacak / sedang viral)
- [x] Filter kategori (Hashtag aktif; Sound/Video "segera") + toggle "Hanya viral"
- **Done when:** buka browser, tren dari DB tampil rapih. ✅ Diverifikasi (screenshot) — **siap dipamerin ke calon klien**.
- ⏳ Nanti: HTMX live-refresh, halaman detail + grafik histori.

### M6 — Deteksi gaya editing Level 1  ⏱️ ~1 sesi
- [ ] `editing.py`: map hashtag/sound → label gaya edit (jedag-jedug, slow-mo, transisi, dll)
- [ ] Tampilkan label di dashboard per tren
- **Done when:** tiap video tren punya tebakan gaya edit dari metadata.

### M7 — Scheduler harian  ⏱️ ~1 sesi
- [ ] APScheduler jalanin `pipeline.py` tiap hari (mis. jam 6 pagi)
- [ ] Log sukses/gagal + fallback kalau sumber diblok
- **Done when:** data kebarui otomatis tanpa jalanin manual.

> Setelah M0–M7 = **MVP USP #1 jalan**. Baru lanjut: perluas vertikal (fashion), prediksi (USP 2), editing Level 2 (computer vision).

---

## 4. Setup Lokal (diisi pas M0)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
cp .env.example .env          # isi config
python scripts/run_once.py    # tes pipeline sekali
uvicorn app.api:app --reload  # nyalain API + dashboard
```

---

## 5. Keputusan Terbuka & Risiko

- **Sumber scrape TikTok** — **mulai dari Creative Center via httpx** (§1b). Kalau kena blok → Playwright → Apify. Scrape app konsumen ditunda ke fase 2 (butuh proxy). Modular by design.
- **Legal** — ambil metrik/metadata publik, **bukan** menyalin konten. Patuhi UU PDP + hak cipta.
- **Target klien** (brand besar vs UMKM) — belum dikunci, ga blokir dev MVP.
- **Migrasi Postgres + Next.js** — ditunda sampai MVP kebukti laku.

---

## 6. Langkah Berikutnya (mulai dari sini)

👉 **M0 — Setup proyek.** Bikin virtualenv, `requirements.txt`, `.gitignore`, `config.py`, scaffold folder.

> Update: centang checkbox di atas tiap milestone kelar. Satu milestone = satu cicilan.
