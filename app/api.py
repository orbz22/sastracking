from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
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
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
templates = Jinja2Templates(directory="app/web/templates")


def _compact(n) -> str:
    """1234 -> 1.2K ; 59400000 -> 59.4M."""
    if n is None:
        return "-"
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))


templates.env.filters["compact"] = _compact


def _row(trend: Trend, snaps: list[Snapshot]) -> dict:
    m = compute(snaps)
    return {
        "id": trend.id,
        "name": trend.name,
        "category": trend.category,
        "industry": trend.industry,
        "region": trend.region,
        "url": trend.url,
        **m,
    }


def _collect(
    session: Session,
    category: str,
    region: str | None,
    only_viral: bool,
    limit: int = 200,
    industry: str | None = None,
) -> list[dict]:
    q = select(Trend).where(Trend.category == category)
    if region:
        q = q.where(Trend.region == region)
    if industry:
        q = q.where(Trend.industry == industry)
    rows: list[dict] = []
    for t in session.exec(q).all():
        snaps = session.exec(select(Snapshot).where(Snapshot.trend_id == t.id)).all()
        row = _row(t, snaps)
        if only_viral and not row["is_viral"]:
            continue
        rows.append(row)
    rows.sort(
        key=lambda r: (
            not r["is_viral"],
            -(r["velocity"] or 0),
            r["rank"] if r["rank"] is not None else 9999,
        )
    )
    return rows[:limit]


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "region": settings.region}


@app.get("/trends")
def list_trends(
    category: str = "hashtag",
    region: str | None = None,
    industry: str | None = None,
    only_viral: bool = False,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    rows = _collect(session, category, region, only_viral, limit, industry)
    return {"count": len(rows), "category": category, "trends": rows}


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


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    category: str = "hashtag",
    industry: str | None = None,
    only_viral: bool = False,
    session: Session = Depends(get_session),
):
    rows = _collect(session, category, settings.region, only_viral, industry=industry)
    viral_count = sum(1 for r in rows if r["is_viral"])
    # daftar industri yang tersedia (buat tombol filter)
    industries = sorted(
        {t.industry for t in session.exec(select(Trend)).all() if t.industry}
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "region": settings.region,
            "vertical": settings.vertical.upper(),
            "category": category,
            "only_viral": only_viral,
            "trends": rows,
            "viral_count": viral_count,
            "industries": industries,
            "industry": industry,
        },
    )
