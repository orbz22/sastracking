"""Job refresh data di background.

Scrape butuh ~3 menit dan membuka jendela Chrome, jadi tidak boleh dijalankan
langsung di dalam request HTTP. Job dijalankan di thread terpisah; dashboard
cukup menanyakan statusnya.
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


def start_refresh(**kwargs) -> bool:
    """Mulai refresh. False kalau job lain masih jalan."""
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
    threading.Thread(target=_run, args=(kwargs,), daemon=True).start()
    return True
