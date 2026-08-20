"""Job refresh data di background.

Scrape butuh puluhan menit (sapuan penuh: periode × semua industri) dan membuka
jendela Chrome, jadi tidak boleh dijalankan langsung di dalam request HTTP. Job
dijalankan di thread terpisah; dashboard cukup menanyakan statusnya.

kwargs diteruskan apa adanya ke run_pipeline (platform, periods, industries, ...).
"""

import math
import threading
from datetime import datetime

from app.config import settings
from app.pipeline import run_pipeline

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
    "eta": None,  # perkiraan detik, buat ditampilkan di dashboard
}


def _eta_list(combos: int, details: int) -> int:
    """Perkiraan durasi job dalam detik, dihitung dari beban — bukan angka mati.

    Dasarnya hasil ukur 2026-08-04 dengan parallel_tabs=4: satu gelombang berisi
    `tabs` kombinasi selesai ~50 detik, dan satu hashtag detail ~28 detik per tab.
    Dulu UI menulis "~3 menit" untuk semua jenis job; itu meleset 5x untuk sapuan
    penuh (45 kombinasi) dan bikin orang mengira job-nya hang.
    """
    tabs = max(1, settings.parallel_tabs)
    detik = math.ceil(combos / tabs) * 50
    if details:
        detik += math.ceil(details / tabs) * 28
    return detik


def status() -> dict:
    with _lock:
        s = dict(_state)
    if s["running"] and s["started_at"]:
        s["elapsed"] = int((datetime.now() - s["started_at"]).total_seconds())
    else:
        s["elapsed"] = None
    eta = s.get("eta")
    if eta:
        s["eta_text"] = f"~{eta} detik" if eta < 90 else f"~{round(eta / 60)} menit"
        # kalau sudah lewat perkiraan, jangan berbohong — bilang apa adanya
        if s["elapsed"] and s["elapsed"] > eta:
            s["eta_text"] = "lebih lama dari perkiraan"
    else:
        s["eta_text"] = None
    for k in ("started_at", "finished_at"):
        if s[k]:
            s[k] = s[k].strftime("%d %b %H:%M")
    return s


def _run(kwargs: dict) -> None:
    try:
        result = run_pipeline(**kwargs)
        err = None
    except Exception as e:  # simpan pesan biar kelihatan di dashboard
        result, err = None, f"{type(e).__name__}: {e}"[:300]
    with _lock:
        _state.update(
            running=False,
            finished_at=datetime.now(),
            result=result,
            error=err,
        )


def _run_details(kwargs: dict) -> None:
    """Tarik kurva massal — pakai slot job yang sama biar tidak rebutan browser."""
    from sqlmodel import Session

    from app.db import engine, init_db
    from app.detail import sync_many

    try:
        init_db()
        with Session(engine) as s:
            result = sync_many(s, **kwargs)
        err = None
    except Exception as e:
        result, err = None, f"{type(e).__name__}: {e}"[:300]
    with _lock:
        _state.update(
            running=False, finished_at=datetime.now(), result=result, error=err
        )


def _start(target, kwargs: dict, eta: int | None = None) -> bool:
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True,
            started_at=datetime.now(),
            finished_at=None,
            result=None,
            error=None,
            eta=eta,
        )
    threading.Thread(target=target, args=(kwargs,), daemon=True).start()
    return True


def start_refresh(**kwargs) -> bool:
    """Mulai refresh. False kalau job lain masih jalan."""
    from app.scrapers.registry import get_platform

    plat = get_platform(kwargs.get("platform") or settings.platform)
    periods = kwargs.get("periods") or (7, 30, 90)
    industries = kwargs.get("industries") or plat.industries
    eta = _eta_list(len(periods) * len(industries), kwargs.get("details", 0))
    return _start(_run, kwargs, eta)


def start_details(**kwargs) -> bool:
    """Mulai tarik kurva massal. False kalau job lain masih jalan."""
    return _start(_run_details, kwargs, _eta_list(0, kwargs.get("limit", 0)))
