"""Ambil + simpan detail satu tren dari sumbernya, on-demand.

Dipisah dari pipeline karena sifatnya beda: pipeline itu sapuan massal terjadwal,
ini dipanggil satu-satu waktu user membuka halaman tren. Butuh ~20 detik karena
kurvanya harus disapu lewat tooltip (lihat CreativeCenterScraper._sweep_chart).
"""

from datetime import datetime

from sqlmodel import Session, select

from app.models import InterestPoint, Trend
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


def interest_series(s: Session, trend_id: int, period: int = 7) -> list[InterestPoint]:
    return sorted(
        s.exec(
            select(InterestPoint).where(
                InterestPoint.trend_id == trend_id, InterestPoint.period == period
            )
        ).all(),
        key=lambda p: p.on_date,
    )
