"""Metrik viral + ambang 'sedang viral' + status naik/puncak/turun.

Dihitung dari histori Snapshot (urut menaik per tanggal). Data tersedia:
views, video_count (posts), rank. Like/share/komentar belum ada -> engagement
true ditunda ke fase enrichment; sementara pakai proxy views_per_post.

Ambang bersifat KALIBRASI KASAR — sesuaikan setelah data beberapa minggu ngalir.
"""

from dataclasses import dataclass
from math import ceil

from app.models import Snapshot


@dataclass(frozen=True)
class ViralThresholds:
    min_views: int = 1_000_000        # dipakai HANYA buat kohort kecil (lihat mark_viral)
    min_velocity: float = 500_000.0   # idem
    up_rate: float = 0.10             # >10%/hari => naik
    down_rate: float = -0.05          # <-5%/hari => turun
    top_pct: float = 0.10             # viral = 10% teratas dalam kohortnya
    min_cohort: int = 5               # di bawah ini, persentil ga bermakna


def series(snaps: list[Snapshot], prefer: tuple[int, ...] = (7, 30, 90)) -> list[Snapshot]:
    """Ambil satu deret dengan period seragam.

    Views period 7 vs 90 hari tidak sebanding (90 hari bersifat kumulatif), jadi
    metrik hanya dihitung dari snapshot ber-period sama. Pilih period terpendek
    yang tersedia — paling responsif terhadap perubahan.
    """
    if not snaps:
        return []
    available = {getattr(s, "period", 7) for s in snaps}
    for p in prefer:
        if p in available:
            return [s for s in snaps if getattr(s, "period", 7) == p]
    return snaps


def _last_two(snaps: list[Snapshot]) -> tuple[Snapshot | None, Snapshot | None]:
    s = sorted(series(snaps), key=lambda x: x.captured_on)
    if len(s) < 2:
        return (None, s[-1] if s else None)
    return (s[-2], s[-1])


def views_velocity(snaps: list[Snapshot]) -> float | None:
    """Δviews per hari antara dua snapshot terakhir."""
    prev, last = _last_two(snaps)
    if prev is None or last is None or prev.views is None or last.views is None:
        return None
    days = (last.captured_on - prev.captured_on).days or 1
    return (last.views - prev.views) / days


def growth_rate(snaps: list[Snapshot]) -> float | None:
    """Pertumbuhan views relatif per hari, mis. 0.18 = +18%/hari."""
    prev, last = _last_two(snaps)
    if prev is None or last is None or not prev.views or last.views is None:
        return None
    days = (last.captured_on - prev.captured_on).days or 1
    return (last.views - prev.views) / prev.views / days


def rank_delta(snaps: list[Snapshot]) -> int | None:
    """Positif = naik peringkat (angka rank mengecil)."""
    prev, last = _last_two(snaps)
    if prev is None or last is None or prev.rank is None or last.rank is None:
        return None
    return prev.rank - last.rank


def views_per_post(snaps: list[Snapshot]) -> float | None:
    """Proxy jangkauan: views / jumlah video. Bukan engagement true."""
    s = series(snaps)
    last = sorted(s, key=lambda x: x.captured_on)[-1] if s else None
    if last is None or not last.video_count or last.views is None:
        return None
    return last.views / last.video_count


def status(snaps: list[Snapshot], th: ViralThresholds) -> str:
    """baru | naik | puncak | turun."""
    g = growth_rate(snaps)
    if g is None:
        return "baru"          # data < 2 hari, belum bisa dinilai
    if g > th.up_rate:
        return "naik"
    if g < th.down_rate:
        return "turun"
    return "puncak"


def is_viral(snaps: list[Snapshot], th: ViralThresholds) -> bool:
    s = series(snaps)
    last = sorted(s, key=lambda x: x.captured_on)[-1] if s else None
    if last is None or last.views is None or last.views < th.min_views:
        return False
    v = views_velocity(snaps)
    # kalau baru 1 hari (velocity None) tapi views sudah besar -> tetap kandidat
    return v is None or v >= th.min_velocity


def mark_viral(rows: list[dict], th: ViralThresholds | None = None) -> list[dict]:
    """Tandai `is_viral` secara RELATIF: 10% teratas dalam kohortnya sendiri.

    Kohort = (industri, jendela/period). Alasan tidak pakai ambang absolut:
    setelah login, satu kombinasi mengembalikan 100 baris — ambang 1 juta views
    meloloskan 96 dari 100, jadi tidak memisahkan apa pun. Basis persentil juga
    adil antar-industri: F&B tidak dibandingkan dengan Games yang volumenya
    beda kelas, dan ikut menyesuaikan sendiri kalau volume TikTok bergeser.

    Dua kolam terpisah di tiap kohort:
      - punya velocity  -> diurut velocity (momentum, sinyal "viral SEKARANG")
      - belum ada velocity (data <2 hari) -> diurut views, biar tren baru tetap
        bisa muncul dan tidak tenggelam cuma karena historinya belum ada
    Industri dengan < `min_cohort` baris digabung jadi satu kohort "sisa" per
    jendela, bukan dibiarkan pakai ambang absolut — kalau dibiarkan, industri
    berisi 2 baris otomatis meloloskan 1 baris sebagai viral (top 10% dari 2
    selalu >= 1), dan itu yang bikin angka flag membengkak.

    Mengubah `rows` di tempat dan mengembalikannya.
    """
    th = th or ViralThresholds()
    cohorts: dict[tuple, list[dict]] = {}
    for r in rows:
        cohorts.setdefault((r.get("industry"), r.get("period")), []).append(r)

    # gabung industri bervolume tipis ke kohort sisa per jendela
    merged: dict[tuple, list[dict]] = {}
    for (ind, period), members in cohorts.items():
        key = (ind, period) if len(members) >= th.min_cohort else ("__sisa__", period)
        merged.setdefault(key, []).extend(members)

    for members in merged.values():
        if len(members) < th.min_cohort:
            continue  # tetap terlalu tipis -> biarkan ambang absolut dari compute()
        for key in ("velocity", "views"):
            pool = [
                m
                for m in members
                if (m.get("velocity") is not None) == (key == "velocity")
                and m.get(key) is not None
            ]
            if not pool:
                continue
            pool.sort(key=lambda m: m[key], reverse=True)
            cut = max(1, ceil(len(pool) * th.top_pct))
            for i, m in enumerate(pool):
                m["is_viral"] = i < cut
                m["cohort_rank"] = i + 1
                m["cohort_size"] = len(pool)
    return rows


def compute(snaps: list[Snapshot], th: ViralThresholds | None = None) -> dict:
    """Ringkasan semua metrik buat satu trend."""
    th = th or ViralThresholds()
    s = series(snaps)
    last = sorted(s, key=lambda x: x.captured_on)[-1] if s else None
    return {
        "views": last.views if last else None,
        "video_count": last.video_count if last else None,
        "rank": last.rank if last else None,
        "velocity": views_velocity(snaps),
        "growth_rate": growth_rate(snaps),
        "rank_delta": rank_delta(snaps),
        "views_per_post": views_per_post(snaps),
        "status": status(snaps, th),
        "is_viral": is_viral(snaps, th),
        "history_days": len(series(snaps)),
        "period": getattr(last, "period", None) if last else None,
    }
