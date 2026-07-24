"""Satu run harian: scrape -> upsert Trend -> insert Snapshot harian.

Idempoten per (trend, tanggal, period): jalanin 2x di hari sama = update, bukan duplikat.
Kumpulan Snapshot lintas hari = histori (aset prediksi).

Tanpa login, Creative Center hanya menampilkan ~3 baris per kombinasi filter.
Karena itu pipeline menyapu beberapa periode (7/30/90 hari) — cara sah menambah
cakupan tanpa menembus batas login. Views antar-period TIDAK sebanding
(7 hari vs 90 hari kumulatif), jadi period ikut disimpan di tiap snapshot.
"""

from datetime import date

from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import Snapshot, Trend
from app.scrapers.creative_center import CreativeCenterScraper


def run_pipeline(
    categories: tuple[str, ...] = ("hashtag",),
    periods: tuple[int, ...] = (7, 30, 90),
    region: str | None = None,
) -> dict:
    init_db()
    scraper = CreativeCenterScraper()
    new_trends = 0
    snaps = 0
    today = date.today()

    with Session(engine) as s:
        for category in categories:
            for period in periods:
                items = scraper.fetch_trends(
                    category=category, period=period, region=region
                )
                for it in items:
                    trend = s.exec(
                        select(Trend).where(
                            Trend.external_id == it["external_id"],
                            Trend.category == it["category"],
                            Trend.region == it["region"],
                        )
                    ).first()
                    if trend is None:
                        trend = Trend(
                            external_id=it["external_id"],
                            category=it["category"],
                            name=it["name"],
                            industry=it.get("industry"),
                            url=it.get("url"),
                            region=it["region"],
                            vertical="fnb",
                        )
                        s.add(trend)
                        s.commit()
                        s.refresh(trend)
                        new_trends += 1

                    snap = s.exec(
                        select(Snapshot).where(
                            Snapshot.trend_id == trend.id,
                            Snapshot.captured_on == today,
                            Snapshot.period == period,
                        )
                    ).first()
                    if snap is None:
                        snap = Snapshot(
                            trend_id=trend.id, captured_on=today, period=period
                        )
                    snap.views = it.get("views")
                    snap.video_count = it.get("posts")
                    snap.rank = it.get("rank")
                    s.add(snap)
                    s.commit()
                    snaps += 1

    return {"new_trends": new_trends, "snapshots": snaps}


if __name__ == "__main__":
    print(run_pipeline())
