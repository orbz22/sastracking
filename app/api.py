from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session, init_db
from app.metrics import compute
from app.models import Snapshot, Trend


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


def _row(trend: Trend, snaps: list[Snapshot]) -> dict:
    m = compute(snaps)
    return {
        "id": trend.id,
        "name": trend.name,
        "category": trend.category,
        "industry": trend.industry,
        "region": trend.region,
        "url": trend.url,
        **m,  # views, velocity, growth_rate, rank, status, is_viral, ...
    }


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "region": settings.region}


@app.get("/trends")
def list_trends(
    category: str = "hashtag",
    region: str | None = None,
    only_viral: bool = False,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    q = select(Trend).where(Trend.category == category)
    if region:
        q = q.where(Trend.region == region)

    rows: list[dict] = []
    for t in session.exec(q).all():
        snaps = session.exec(select(Snapshot).where(Snapshot.trend_id == t.id)).all()
        row = _row(t, snaps)
        if only_viral and not row["is_viral"]:
            continue
        rows.append(row)

    # urutan: viral dulu, lalu velocity tertinggi, lalu rank terkecil
    rows.sort(
        key=lambda r: (
            not r["is_viral"],
            -(r["velocity"] or 0),
            r["rank"] if r["rank"] is not None else 9999,
        )
    )
    return {"count": len(rows[:limit]), "category": category, "trends": rows[:limit]}


@app.get("/trends/{trend_id}")
def trend_detail(trend_id: int, session: Session = Depends(get_session)):
    trend = session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(status_code=404, detail="trend tidak ditemukan")
    snaps = sorted(
        session.exec(select(Snapshot).where(Snapshot.trend_id == trend.id)).all(),
        key=lambda x: x.captured_on,
    )
    detail = _row(trend, snaps)
    detail["history"] = [
        {
            "date": s.captured_on.isoformat(),
            "views": s.views,
            "video_count": s.video_count,
            "rank": s.rank,
        }
        for s in snaps
    ]
    return detail
