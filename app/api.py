import base64
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app import charts, jobs
from app.config import settings
from app.detail import interest_series, refresh_detail
from app.db import get_session, init_db
from app.metrics import compute, mark_viral
from app.models import Snapshot, Trend
from app.qr import qr_svg
from app.scrapers.creative_center import CreativeCenterScraper
from app.scrapers.registry import DEFAULT_PLATFORM, PLATFORMS, get_platform


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
templates = Jinja2Templates(directory="app/web/templates")


@app.middleware("http")
async def _gerbang(request: Request, call_next):
    """Autentikasi + kunci tulis. Dipakai waktu app dibuka lewat tunnel.

    Tanpa ini, siapa pun yang tahu URL ngrok bisa menekan /refresh dan
    menjalankan Chrome dengan sesi TikTok pemilik mesin. Kalau AUTH_USER kosong
    gerbang dilewati sepenuhnya, jadi jalan lokal tetap seperti biasa.
    """
    # Tanpa gerbang (jalan lokal) pemakainya = pemilik mesin, jadi boleh apa saja.
    admin = True

    if settings.auth_user:
        nama = sandi = ""
        head = request.headers.get("authorization", "")
        if head.startswith("Basic "):
            try:
                nama, _, sandi = (
                    base64.b64decode(head[6:]).decode("utf-8").partition(":")
                )
            except Exception:  # noqa: BLE001 — header rusak = gagal, titik
                nama = sandi = ""

        # compare_digest: hindari bocornya panjang/isi sandi lewat timing.
        # Kedua cek selalu dijalankan supaya waktu responsnya tidak membocorkan
        # akun mana yang cocok.
        penonton = secrets.compare_digest(
            nama, settings.auth_user
        ) and secrets.compare_digest(sandi, settings.auth_pass)
        admin = bool(settings.admin_pass) and (
            secrets.compare_digest(nama, settings.admin_user)
            and secrets.compare_digest(sandi, settings.admin_pass)
        )
        if not (penonton or admin):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="SAS Tracking"'},
            )

    # read_only mengunci penonton, bukan pemegang kredensial admin
    boleh_tulis = admin or not settings.read_only
    request.state.read_only = not boleh_tulis

    if not boleh_tulis and request.method not in ("GET", "HEAD", "OPTIONS"):
        return Response(status_code=403, content="Mode lihat-saja: aksi dimatikan.")

    return await call_next(request)


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


# Batas baris tabel dashboard. Cuma memotong TAMPILAN — semua statistik di
# atasnya tetap dihitung dari seluruh baris hasil filter.
TABLE_LIMIT = 200

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
    limit: int | None = 200,
    industry: str | None = None,
    period: int | None = None,
    platform: str = DEFAULT_PLATFORM,
) -> list[dict]:
    """limit=None mengembalikan SEMUA baris.

    Penting buat statistik: baris diurutkan viral-duluan, jadi menghitung
    persentase dari hasil yang sudah dipotong selalu memberi angka ngawur
    (pernah kejadian: "200 dari 200 viral, 100%").
    """
    q = select(Trend).where(
        Trend.platform == platform, Trend.category == category
    )
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
    return rows if limit is None else rows[:limit]


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
    platform: str = Query(DEFAULT_PLATFORM, description="tiktok | instagram | youtube"),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    rows = _collect(
        session, category, region, only_viral, limit, industry, period, platform
    )
    return {
        "count": len(rows),
        "platform": platform,
        "category": category,
        "period": period,
        "trends": rows,
    }


@app.get("/platforms")
def list_platforms():
    """Platform yang terdaftar + status ketersediaan scraper-nya."""
    return [
        {
            "key": p.key,
            "label": p.label,
            "available": p.available,
            "categories": list(p.categories),
            "industries": len(p.industries),
            "note": p.note,
        }
        for p in PLATFORMS.values()
    ]


@app.get("/t/{trend_id}", response_class=HTMLResponse)
def trend_page(
    request: Request,
    trend_id: int,
    period: int | None = None,
    session: Session = Depends(get_session),
):
    """Halaman detail satu tren — padanan 'See analytics' di Creative Center."""
    trend = session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(status_code=404, detail="tren tidak ditemukan")

    snaps = sorted(
        session.exec(select(Snapshot).where(Snapshot.trend_id == trend.id)).all(),
        key=lambda x: x.captured_on,
    )
    # Jangan paksa 7 hari: banyak tren cuma ke-scrape di jendela 30/90, dan
    # halamannya jadi ngaco — kartu nampilin angka 90 hari sementara tab kurva
    # bilang 7 hari. Pilih jendela terpendek yang trennya benar-benar punya.
    available = sorted({s.period for s in snaps})
    if period not in available:
        period = available[0] if available else 7
    # is_viral itu peringkat relatif, jadi tren ini harus diadu dengan kohortnya
    # dulu. Kalau cuma _row() sendirian, yang kepakai ambang absolut dan kartu
    # status bakal mengklaim "10% teratas" tanpa pernah membandingkan apa pun.
    cohort = _collect(
        session,
        trend.category,
        trend.region,
        only_viral=False,
        limit=100_000,
        industry=trend.industry,
        period=period,
        platform=trend.platform,
    )
    row = next((r for r in cohort if r["id"] == trend.id), None) or _row(trend, snaps)
    points = interest_series(session, trend.id, period)

    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={
            "app_name": settings.app_name,
            # per-permintaan, bukan global: admin melihat tombolnya aktif
            # walaupun penonton lain di link yang sama melihatnya mati
            "read_only": getattr(request.state, "read_only", settings.read_only),
            "region": settings.region,
            "platform": get_platform(trend.platform),
            "platforms": list(PLATFORMS.values()),
            "trend": trend,
            "row": row,
            "period": period,
            # halaman sumber selalu ada selama source_id terekam; halaman tag
            # publik tidak selalu (lihat catatan di template)
            # QR di-scan dari layar laptop -> hashtag kebuka di aplikasi HP,
            # yang terbukti jalan sementara halaman web-nya sering kosong
            "qr": qr_svg(trend.url) if trend.url else None,
            "source_url": (
                f"{CreativeCenterScraper.DETAIL_URL.format(id=trend.source_id)}"
                f"?region={trend.region}&period={period}"
                if trend.source_id and trend.platform == "tiktok"
                else None
            ),
            "available_periods": available,
            # kurva sumber (indeks 0-100) vs histori kita sendiri (views absolut)
            "interest": charts.line_chart([(p.on_date, p.value) for p in points]),
            "points": points,
            "own_history": [
                {"date": s.captured_on, "views": s.views, "period": s.period}
                for s in snaps
                if s.period == period
            ],
            "job": jobs.status(),
        },
    )


@app.post("/t/{trend_id}/sync")
def trend_sync(trend_id: int, period: int = 7, session: Session = Depends(get_session)):
    """Tarik ulang detail dari sumber SEKARANG (bukan nunggu sapuan harian)."""
    trend = session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(status_code=404, detail="tren tidak ditemukan")
    try:
        refresh_detail(session, trend, period)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return RedirectResponse(f"/t/{trend_id}?period={period}", status_code=303)


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
def refresh(
    quick: bool = False,
    platform: str = DEFAULT_PLATFORM,
    details: int = Query(50, ge=0, le=500, description="jumlah kurva ikut ditarik"),
):
    """Mulai ambil data baru di background lalu balik ke dashboard.

    Satu tombol menarik semuanya: daftar tren + snapshot harian + kurva. Dulu
    kurva punya tombol sendiri dan gampang lupa diklik, jadi kurvanya basi.

    quick=True: hanya F&B periode 7 hari buat cek cepat — kurva dilewati supaya
    tetap cepat.
    """
    kwargs: dict = {"platform": platform, "details": 0 if quick else details}
    if quick:
        kwargs |= {"periods": (7,), "industries": ("Food & Beverage",)}
    jobs.start_refresh(**kwargs)  # kalau sudah jalan, diabaikan
    return RedirectResponse(f"/?platform={platform}", status_code=303)


@app.post("/details/sync")
def details_sync(
    limit: int = Query(50, ge=1, le=500),
    period: int = 7,
    platform: str = DEFAULT_PLATFORM,
):
    """Tarik kurva massal tanpa scrape ulang list-nya (job background)."""
    jobs.start_details(limit=limit, period=period, platform=platform)
    return RedirectResponse(f"/?platform={platform}", status_code=303)


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
    platform: str = DEFAULT_PLATFORM,
    session: Session = Depends(get_session),
):
    plat = get_platform(platform)
    category = category if category in plat.categories else plat.categories[0]
    # semua baris dulu -> statistik dihitung dari sini; tabel baru dipotong
    all_rows = _collect(
        session,
        category,
        settings.region,
        only_viral,
        limit=None,
        industry=industry,
        period=period,
        platform=plat.key,
    )
    viral_count = sum(1 for r in all_rows if r["is_viral"])
    rising = sum(1 for r in all_rows if r["status"] == "naik")
    total_views = sum(r["views"] or 0 for r in all_rows)
    rows = all_rows[:TABLE_LIMIT]

    # Deret harian buat sparkline KPI (butuh >=2 hari data). WAJIB dikunci ke
    # satu jendela: kalau dicampur, hari yang kebetulan punya snapshot 90-hari
    # (kumulatif) bikin totalnya melonjak dan delta%-nya jadi omong kosong.
    spark_period = period or 7
    ids = [r["id"] for r in all_rows]
    snaps = (
        list(
            session.exec(
                select(Snapshot).where(
                    Snapshot.trend_id.in_(ids), Snapshot.period == spark_period
                )
            ).all()
        )
        if ids
        else []
    )
    daily = charts.daily_totals(snaps)

    # industri yang benar-benar ada datanya di platform ini (buat tombol filter)
    industries = sorted(
        {
            t.industry
            for t in session.exec(
                select(Trend).where(Trend.platform == plat.key)
            ).all()
            if t.industry
        }
    )
    # berapa tren yang siap ditarik kurvanya (butuh id sumber) — biar user tahu
    # kenapa "Tarik kurva" cuma menyentuh sebagian
    ready = sum(1 for t in session.exec(
        select(Trend).where(Trend.platform == plat.key)
    ).all() if t.source_id)

    state = {
        "category": category,
        "industry": industry,
        "only_viral": only_viral,
        "period": period,
        "metric": metric,
        "platform": plat.key if plat.key != DEFAULT_PLATFORM else None,
    }
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            # per-permintaan, bukan global: admin melihat tombolnya aktif
            # walaupun penonton lain di link yang sama melihatnya mati
            "read_only": getattr(request.state, "read_only", settings.read_only),
            "region": settings.region,
            "platform": plat,
            "platforms": list(PLATFORMS.values()),
            "category": category,
            "only_viral": only_viral,
            "trends": rows,
            "total_rows": len(all_rows),
            "table_limit": TABLE_LIMIT,
            "viral_count": viral_count,
            "rising": rising,
            "total_views": total_views,
            "industries": industries,
            "industry": industry,
            "period": period,
            "metric": metric,
            "state": state,
            "ready_for_curve": ready,
            "job": jobs.status(),
            # semuanya dari all_rows: peringkat & komposisi harus dihitung dari
            # seluruh baris, bukan dari 200 yang kebetulan tampil di tabel
            "bars": charts.rank_bars(all_rows, metric),
            "ind_rank": charts.by_industry(all_rows),
            "mix": charts.status_mix(all_rows),
            "spark_views": charts.sparkline([d[1] for d in daily]),
            "spark_trends": charts.sparkline([float(d[2]) for d in daily]),
            "days": len(daily),
            "spark_period": spark_period,
            "last_day": daily[-1][0].isoformat() if daily else None,
        },
    )
