from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app import charts, jobs
from app.config import settings
from app.db import get_session, init_db
from app.metrics import compute, mark_viral
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


def _pct(x, digits: int = 0) -> str:
    """0.183 -> +18%. Dipakai buat growth rate."""
    if x is None:
        return "-"
    return f"{x * 100:+.{digits}f}%"


def _q(base: dict, **over) -> str:
    """Bangun URL dashboard dari state sekarang + perubahan (buat link filter)."""
    merged = {**base, **over}
    clean = {k: v for k, v in merged.items() if v not in (None, "", False)}
    return "/?" + urlencode(clean) if clean else "/"


templates.env.filters["compact"] = _compact
templates.env.filters["pct"] = _pct
templates.env.globals["q"] = _q


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
    period: int | None = None,
) -> list[dict]:
    q = select(Trend).where(Trend.category == category)
    if region:
        q = q.where(Trend.region == region)
    if industry:
        q = q.where(Trend.industry == industry)
    trends = list(session.exec(q).all())

    # satu query buat semua snapshot lalu dikelompokkan di Python. Sebelumnya
    # satu query per tren (N+1) — ga kerasa di 79 tren, berat di ribuan.
    by_trend: dict[int, list[Snapshot]] = {}
    if trends:
        ids = [t.id for t in trends]
        sq = select(Snapshot).where(Snapshot.trend_id.in_(ids))
        if period:
            sq = sq.where(Snapshot.period == period)
        for s in session.exec(sq).all():
            by_trend.setdefault(s.trend_id, []).append(s)

    rows: list[dict] = []
    for t in trends:
        snaps = by_trend.get(t.id, [])
        # jendela dikunci di query di atas: tren tanpa snapshot di period itu
        # ikut hilang, bukan jatuh ke period lain (views antar-period nggak sebanding)
        if period and not snaps:
            continue
        rows.append(_row(t, snaps))

    # penandaan viral bersifat relatif terhadap kohort, jadi harus lihat SEMUA
    # baris dulu — baru boleh disaring only_viral
    mark_viral(rows)
    if only_viral:
        rows = [r for r in rows if r["is_viral"]]

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
    period: int | None = Query(None, description="jendela sumber: 7 / 30 / 90 hari"),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    rows = _collect(session, category, region, only_viral, limit, industry, period)
    return {"count": len(rows), "category": category, "period": period, "trends": rows}


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


@app.post("/refresh")
def refresh(quick: bool = False):
    """Mulai ambil data baru di background lalu balik ke dashboard.

    quick=True: hanya F&B periode 7 hari (~30 detik) buat cek cepat.
    """
    kwargs = (
        {"periods": (7,), "industries": ("Food & Beverage",)} if quick else {}
    )
    jobs.start_refresh(**kwargs)  # kalau sudah jalan, diabaikan
    return RedirectResponse("/", status_code=303)


@app.get("/refresh/status")
def refresh_status():
    return jobs.status()


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    category: str = "hashtag",
    industry: str | None = None,
    only_viral: bool = False,
    period: int | None = Query(None, description="jendela sumber: 7 / 30 / 90 hari"),
    metric: str = Query("views", pattern="^(views|velocity)$"),
    session: Session = Depends(get_session),
):
    rows = _collect(
        session,
        category,
        settings.region,
        only_viral,
        industry=industry,
        period=period,
    )
    viral_count = sum(1 for r in rows if r["is_viral"])
    rising = sum(1 for r in rows if r["status"] == "naik")
    total_views = sum(r["views"] or 0 for r in rows)

    # deret harian buat sparkline kartu KPI (butuh >=2 hari data)
    ids = [r["id"] for r in rows]
    snaps = (
        list(session.exec(select(Snapshot).where(Snapshot.trend_id.in_(ids))).all())
        if ids
        else []
    )
    if period:
        snaps = [s for s in snaps if s.period == period]
    daily = charts.daily_totals(snaps)

    # daftar industri yang tersedia (buat tombol filter)
    industries = sorted(
        {t.industry for t in session.exec(select(Trend)).all() if t.industry}
    )
    state = {
        "category": category,
        "industry": industry,
        "only_viral": only_viral,
        "period": period,
        "metric": metric,
    }
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
            "rising": rising,
            "total_views": total_views,
            "industries": industries,
            "industry": industry,
            "period": period,
            "metric": metric,
            "state": state,
            "job": jobs.status(),
            "bars": charts.rank_bars(rows, metric),
            "ind_rank": charts.by_industry(rows),
            "mix": charts.status_mix(rows),
            "spark_views": charts.sparkline([d[1] for d in daily]),
            "spark_trends": charts.sparkline([float(d[2]) for d in daily]),
            "days": len(daily),
            "last_day": daily[-1][0].isoformat() if daily else None,
        },
    )
