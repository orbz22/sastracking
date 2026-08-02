"""Job refresh data di background.

Scrape butuh puluhan menit (sapuan penuh: periode × semua industri) dan membuka
jendela Chrome, jadi tidak boleh dijalankan langsung di dalam request HTTP. Job
dijalankan di thread terpisah; dashboard cukup menanyakan statusnya.

kwargs diteruskan apa adanya ke run_pipeline (platform, periods, industries, ...).
"""

import threading
from datetime import datetime

from app.pipeline import run_pipeline

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


def status() -> dict:
    with _lock:
        s = dict(_state)
    if s["running"] and s["started_at"]:
        s["elapsed"] = int((datetime.now() - s["started_at"]).total_seconds())
    else:
        s["elapsed"] = None
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


def _start(target, kwargs: dict) -> bool:
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True,
            started_at=datetime.now(),
            finished_at=None,
            result=None,
            error=None,
        )
    threading.Thread(target=target, args=(kwargs,), daemon=True).start()
    return True


def start_refresh(**kwargs) -> bool:
    """Mulai refresh. False kalau job lain masih jalan."""
    return _start(_run, kwargs)


def start_details(**kwargs) -> bool:
    """Mulai tarik kurva massal. False kalau job lain masih jalan."""
    return _start(_run_details, kwargs)
