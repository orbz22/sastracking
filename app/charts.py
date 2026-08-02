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


def line_chart(
    points: list[tuple[date, float]],
    w: int = 860,
    h: int = 260,
    pad_l: int = 38,
    pad_r: int = 14,
    pad_t: int = 30,  # ruang buat label puncak di atas garis; 14 bikin kepotong
    pad_b: int = 30,
) -> dict | None:
    """Geometri line chart "Interest over time" (skala Y dikunci 0-100).

    Y sengaja TIDAK diskalakan ke min/max data: nilainya memang indeks 0-100,
    jadi sumbu yang mengambang bikin kenaikan kecil kelihatan dramatis.

    Label X dipilih selektif (~6 tanggal) — kurva 90 hari punya ~40 titik dan
    memberi label semuanya cuma jadi tumpukan teks yang tidak terbaca.
    """
    pts = [(d, v) for d, v in points if v is not None]
    if len(pts) < 2:
        return None

    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    step = iw / (len(pts) - 1)

    def y_of(v: float) -> float:
        return pad_t + ih - (max(0.0, min(100.0, v)) / 100) * ih

    coords = [(pad_l + i * step, y_of(v)) for i, (_, v) in enumerate(pts)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (
        f"M{coords[0][0]:.1f},{pad_t + ih:.1f} "
        + " ".join(f"L{x:.1f},{y:.1f}" for x, y in coords)
        + f" L{coords[-1][0]:.1f},{pad_t + ih:.1f} Z"
    )

    every = max(1, round(len(pts) / 6))
    peak_i = max(range(len(pts)), key=lambda i: pts[i][1])

    # Label X: tiap `every` titik, plus titik terakhir — TAPI titik terakhir
    # dilewati kalau terlalu mepet ke label sebelumnya, kalau tidak teksnya
    # bertabrakan jadi "28/0730/07".
    ticks = set(range(0, len(pts), every))
    if len(pts) - 1 - max(ticks) >= every * 0.6:
        ticks.add(len(pts) - 1)

    return {
        "w": w,
        "h": h,
        "x0": pad_l,
        "x1": pad_l + iw,
        "y0": pad_t,
        "y1": pad_t + ih,
        "line": line,
        "area": area,
        "points": [
            {
                "x": round(coords[i][0], 1),
                "y": round(coords[i][1], 1),
                "date": pts[i][0].strftime("%d/%m/%y"),
                "value": pts[i][1],
                "tick": i in ticks,
                "peak": i == peak_i,
            }
            for i in range(len(pts))
        ],
        "yticks": [{"v": v, "y": round(y_of(v), 1)} for v in (0, 25, 50, 75, 100)],
        "peak": {"date": pts[peak_i][0], "value": pts[peak_i][1]},
        "last": {"date": pts[-1][0], "value": pts[-1][1]},
    }


def daily_totals(
    snaps: list[Snapshot], like_for_like: bool = True
) -> list[tuple[date, int, int]]:
    """[(tanggal, total views, jumlah tren)] urut menaik.

    `like_for_like`: hanya hitung tren yang punya snapshot di SEMUA tanggal.
    Tanpa ini, total harian ikut naik cuma karena cakupan scrape bertambah —
    pernah menghasilkan "+6527%" padahal yang berubah jumlah tren yang
    dilacak (53 -> 3.968), bukan popularitasnya.
    """
    if not snaps:
        return []

    if like_for_like:
        days = {s.captured_on for s in snaps}
        per_trend: dict[int, set[date]] = defaultdict(set)
        for s in snaps:
            per_trend[s.trend_id].add(s.captured_on)
        tetap = {tid for tid, d in per_trend.items() if d == days}
        # kalau tidak ada satu pun tren yang hadir di semua tanggal, deret
        # like-for-like kosong -> lebih baik tidak menampilkan apa pun
        snaps = [s for s in snaps if s.trend_id in tetap]
        if not snaps:
            return []

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
