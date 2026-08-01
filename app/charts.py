"""Helper kecil buat visualisasi: sparkline SVG + agregasi angka dashboard.

Sengaja tanpa library chart — data dashboard masih kecil (<200 baris) dan
render server-side bikin halaman tetap jalan tanpa JavaScript.
"""

from collections import defaultdict
from datetime import date

from app.models import Snapshot


def sparkline(values: list[float], w: int = 112, h: int = 32, pad: int = 4) -> dict | None:
    """Titik-titik polyline + path area buat sparkline.

    Balik None kalau titiknya < 2 — sparkline satu titik itu menyesatkan,
    lebih jujur nampilin placeholder "butuh >=2 hari data".
    """
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return None
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1
    step = (w - pad * 2) / (len(pts) - 1)
    coords = [
        (pad + i * step, h - pad - (v - lo) / span * (h - pad * 2))
        for i, v in enumerate(pts)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"M{coords[0][0]:.1f},{h} " + " ".join(
        f"L{x:.1f},{y:.1f}" for x, y in coords
    ) + f" L{coords[-1][0]:.1f},{h} Z"
    first, last = pts[0], pts[-1]
    return {
        "line": line,
        "area": area,
        "w": w,
        "h": h,
        "dot": coords[-1],
        "delta": (last - first) / first if first else None,
    }


def daily_totals(snaps: list[Snapshot]) -> list[tuple[date, int, int]]:
    """[(tanggal, total views, jumlah tren)] urut menaik."""
    agg: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for s in snaps:
        agg[s.captured_on][0] += s.views or 0
        agg[s.captured_on][1] += 1
    return [(d, v, n) for d, (v, n) in sorted(agg.items())]


def rank_bars(rows: list[dict], key: str, limit: int = 8) -> list[dict]:
    """Baris teratas + lebar bar relatif (persen) terhadap nilai tertinggi."""
    scored = [r for r in rows if (r.get(key) or 0) > 0]
    scored.sort(key=lambda r: r[key], reverse=True)
    top = scored[:limit]
    if not top:
        return []
    peak = top[0][key]
    return [{**r, "pct": max(4.0, r[key] / peak * 100)} for r in top]


def by_industry(rows: list[dict], limit: int = 7) -> list[dict]:
    """Agregat views + jumlah tren per industri, urut views terbesar."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        agg[r.get("industry") or "Tanpa industri"][0] += r.get("views") or 0
        agg[r.get("industry") or "Tanpa industri"][1] += 1
    out = [
        {"name": name, "views": views, "count": count}
        for name, (views, count) in agg.items()
    ]
    out.sort(key=lambda x: x["views"], reverse=True)
    total = sum(x["views"] for x in out) or 1
    for x in out:
        x["share"] = x["views"] / total
    return out[:limit]


def status_mix(rows: list[dict]) -> list[dict]:
    """Komposisi status (naik/puncak/turun/baru) buat bar tipis di kartu KPI."""
    order = ("naik", "puncak", "turun", "baru")
    counts = {k: 0 for k in order}
    for r in rows:
        counts[r.get("status", "baru")] = counts.get(r.get("status", "baru"), 0) + 1
    total = sum(counts.values()) or 1
    return [
        {"key": k, "n": counts[k], "pct": counts[k] / total * 100}
        for k in order
        if counts[k]
    ]
