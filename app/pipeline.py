"""Satu run harian: scrape -> upsert Trend -> insert Snapshot harian.

Idempoten per hari: jalanin 2x di hari sama = update snapshot, bukan duplikat.
Kumpulan Snapshot lintas hari = histori (aset prediksi).
"""

from datetime import date

from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import Snapshot, Trend
from app.scrapers.creative_center import CreativeCenterScraper


def run_pipeline(
    categories: tuple[str, ...] = ("hashtag",),
    period: int = 7,
    region: str | None = None,
) -> dict:
    init_db()
    scraper = CreativeCenterScraper()
    new_trends = 0
    snaps = 0

    with Session(engine) as s:
        for category in categories:
            items = scraper.fetch_trends(category=category, period=period, region=region)
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

                today = date.today()
                snap = s.exec(
                    select(Snapshot).where(
                        Snapshot.trend_id == trend.id,
                        Snapshot.captured_on == today,
                    )
                ).first()
                if snap is None:
                    snap = Snapshot(trend_id=trend.id, captured_on=today)
                snap.views = it.get("views")
                snap.video_count = it.get("posts")
                snap.rank = it.get("rank")
                s.add(snap)
                s.commit()
                snaps += 1

    return {"new_trends": new_trends, "snapshots": snaps}


if __name__ == "__main__":
    print(run_pipeline())
