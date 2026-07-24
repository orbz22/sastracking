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

```bash
# API + health check
uvicorn app.api:app --reload
# buka http://127.0.0.1:8000/health  dan  /docs

# Pipeline manual sekali (M1+)
python -m scripts.run_once
```

## Status

- [x] M0 — Setup proyek (skeleton + API nyala)
- [x] M1 — Scraper Creative Center (DOM/Playwright, headed) — data nyata
- [x] M2 — DB + histori harian (idempoten, histori kebukti)
- [ ] M3 — Metrik viral
- [ ] M4 — API top-tren
- [ ] M5 — Dashboard
- [ ] M6 — Deteksi editing Level 1
- [ ] M7 — Scheduler harian
