"""Ambil + simpan detail satu tren dari sumbernya, on-demand.

Dipisah dari pipeline karena sifatnya beda: pipeline itu sapuan massal terjadwal,
ini dipanggil satu-satu waktu user membuka halaman tren. Butuh ~20 detik karena
kurvanya harus disapu lewat tooltip (lihat CreativeCenterScraper._sweep_chart).
"""

from datetime import datetime

from sqlmodel import Session, select

from app.config import settings
from app.models import InterestPoint, Snapshot, Trend
from app.scrapers.parallel import fetch_details_parallel
from app.scrapers.registry import get_scraper


def refresh_detail(s: Session, trend: Trend, period: int = 7) -> dict:
    """Tarik detail dari sumber lalu simpan kurvanya. Balikin ringkasan."""
    if not trend.source_id:
        raise ValueError(
            "tren ini belum punya id sumber — perlu di-scrape ulang lewat "
            "'Ambil data baru' supaya link detailnya ikut terekam"
        )

    scraper = get_scraper(trend.platform)
    data = scraper.fetch_detail(trend.source_id, region=trend.region, period=period)

    # kurva di-replace, bukan ditambah: sumber mengirim ulang seluruh rentang
    # tiap kali, dan nilainya indeks relatif yang bisa berubah kalau puncaknya
    # bergeser. Menggabung yang lama dengan yang baru = mencampur dua skala.
    old = s.exec(
        select(InterestPoint).where(
            InterestPoint.trend_id == trend.id, InterestPoint.period == period
        )
    ).all()
    for point in old:
        s.delete(point)

    now = datetime.utcnow()
    for pt in data.get("interest", []):
        s.add(
            InterestPoint(
                trend_id=trend.id,
                on_date=pt["date"],
                value=pt["value"],
                period=period,
                fetched_at=now,
            )
        )

    # detail memuat SEMUA industri hashtag ini; daftar sempat terpotong satu
    # waktu di-scrape dari list. Simpan yang pertama sebagai industri utama.
    inds = data.get("industries") or []
    if inds and not trend.industry:
        trend.industry = inds[0]
        s.add(trend)

    s.commit()
    return {
        "name": data.get("name"),
        "industries": inds,
        "posts": data.get("posts"),
        "views": data.get("views"),
        "points": len(data.get("interest", [])),
        "period": period,
    }


def _store(s: Session, trend: Trend, data: dict, period: int) -> int:
    """Tulis kurva satu tren (replace, lihat alasan di refresh_detail)."""
    for point in s.exec(
        select(InterestPoint).where(
            InterestPoint.trend_id == trend.id, InterestPoint.period == period
        )
    ).all():
        s.delete(point)

    now = datetime.utcnow()
    pts = data.get("interest", [])
    for pt in pts:
        s.add(
            InterestPoint(
                trend_id=trend.id,
                on_date=pt["date"],
                value=pt["value"],
                period=period,
                fetched_at=now,
            )
        )
    inds = data.get("industries") or []
    if inds and not trend.industry:
        trend.industry = inds[0]
        s.add(trend)
    return len(pts)


def sync_many(
    s: Session,
    limit: int = 100,
    period: int = 7,
    platform: str = "tiktok",
    only_missing: bool = True,
) -> dict:
    """Tarik kurva untuk banyak tren sekaligus, tanpa perlu diklik satu-satu.

    Menarik SEMUA tren tidak masuk akal (~13 detik × ribuan baris = berjam-jam),
    jadi diprioritaskan: yang punya id sumber, views terbesar duluan. Dipakai
    oleh job harian supaya kurvanya sudah siap sebelum dibuka orang.
    """
    semua = list(s.exec(select(Trend).where(Trend.platform == platform)).all())
    candidates = [t for t in semua if t.source_id]
    # baris lama ke-scrape sebelum id sumber ikut direkam -> nggak bisa dibuka
    # halaman detailnya. Dilaporkan biar jelas kenapa jumlahnya nggak sesuai.
    no_source = len(semua) - len(candidates)

    if only_missing:
        punya = {
            p.trend_id
            for p in s.exec(
                select(InterestPoint).where(InterestPoint.period == period)
            ).all()
        }
        candidates = [t for t in candidates if t.id not in punya]

    # urutkan pakai views snapshot terakhir -> yang paling ramai duluan
    views: dict[int, int] = {}
    for snap in s.exec(
        select(Snapshot).where(Snapshot.period == period)
    ).all():
        views[snap.trend_id] = max(views.get(snap.trend_id, 0), snap.views or 0)
    candidates.sort(key=lambda t: views.get(t.id, 0), reverse=True)
    picked = candidates[:limit]
    if not picked:
        return {"picked": 0, "saved": 0, "points": 0, "tanpa_id_sumber": no_source}

    by_id = {t.source_id: t for t in picked}
    ids = [t.source_id for t in picked]
    if settings.parallel_tabs > 1 and platform == "tiktok":
        got = fetch_details_parallel(ids, region=picked[0].region, period=period)
    else:
        got = get_scraper(platform).fetch_details_many(
            ids,
            region=picked[0].region,
            period=period,
            on_progress=lambda i, n, sid: print(f"  [detail {i}/{n}] {sid}"),
        )

    saved = points = 0
    for sid, data in got.items():
        trend = by_id.get(sid)
        if trend is None:
            continue
        try:
            points += _store(s, trend, data, period)
            s.commit()
            saved += 1
        except Exception as e:  # noqa: BLE001
            s.rollback()
            print(f"[warn] simpan kurva {sid} gagal: {type(e).__name__}: {e}")

    return {
        "picked": len(picked),
        "saved": saved,
        "points": points,
        "period": period,
        "tanpa_id_sumber": no_source,
    }


def interest_series(s: Session, trend_id: int, period: int = 7) -> list[InterestPoint]:
    return sorted(
        s.exec(
            select(InterestPoint).where(
                InterestPoint.trend_id == trend_id, InterestPoint.period == period
            )
        ).all(),
        key=lambda p: p.on_date,
    )
