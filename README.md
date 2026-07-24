# Viral Trend Intelligence — MVP

Modul pertama platform **SA SINC**. Rencana lengkap: [`PLAN.md`](./PLAN.md).

## Setup

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Git Bash:
# source .venv/Scripts/activate

pip install -r requirements.txt
cp .env.example .env
```

## Jalanin

> PENTING: pakai Python dari **.venv** (bukan Python global). Cara paling aman —
> tunjuk python venv langsung, jadi ga perlu aktivasi & ga kena execution-policy:

```powershell
# Dashboard + API  ->  http://127.0.0.1:8000/  (dan /docs, /health)
.venv\Scripts\python.exe -m uvicorn app.api:app --reload

# Pipeline manual sekali (scrape -> DB)  — buka jendela Chrome (headed)
.venv\Scripts\python.exe -m scripts.run_once
```

Kalau mau aktivasi venv dulu (biar bisa ketik `uvicorn`/`python` langsung):

```powershell
.venv\Scripts\Activate.ps1      # kalau ditolak: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
uvicorn app.api:app --reload
```

## Status

- [x] M0 — Setup proyek (skeleton + API nyala)
- [x] M1 — Scraper Creative Center (DOM/Playwright, headed) — data nyata
- [x] M2 — DB + histori harian (idempoten, histori kebukti)
- [x] M3 — Metrik viral (velocity/growth/status/is_viral)
- [x] M4 — API top-tren (`/trends`, `/trends/{id}`)
- [x] M5 — Dashboard (`GET /` — tabel + badge + filter)
- [ ] M6 — Deteksi editing Level 1
- [ ] M7 — Scheduler harian
