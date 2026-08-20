"""Satu run harian: scrape -> upsert Trend -> insert Snapshot harian.

Idempoten per (trend, tanggal, period): jalanin 2x di hari sama = update, bukan duplikat.
Kumpulan Snapshot lintas hari = histori (aset prediksi).

Pipeline tidak menyebut TikTok sama sekali — platform diambil dari
scrapers/registry.py, jadi menambah Instagram/YouTube nanti tidak menyentuh file
ini. Default cakupan: SEMUA industri (bukan lagi khusus F&B).

Satu kombinasi filter = 100 baris (sudah login). Views antar-period TIDAK
sebanding (7 hari vs 90 hari kumulatif), jadi period ikut disimpan di tiap
snapshot dan metrik hanya membandingkan period yang sama.

Penyimpanan dibuat tahan-gagal: satu baris bermasalah tidak boleh menghanguskan
sapuan yang makan puluhan menit (pernah kejadian — constraint NOT NULL sisa
skema lama bikin seluruh hasil scrape terbuang).
"""

from datetime import date

from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.models import Snapshot, Trend
from app.scrapers.parallel import fetch_many_parallel
from app.scrapers.registry import DEFAULT_PLATFORM, get_platform, get_scraper


def _save(s: Session, platform: str, it: dict, today: date) -> bool:
    """Upsert satu tren + snapshot hariannya. True kalau trennya baru."""
    trend = s.exec(
        select(Trend).where(
            Trend.platform == platform,
            Trend.external_id == it["external_id"],
            Trend.category == it["category"],
            Trend.region == it["region"],
        )
    ).first()

    is_new = trend is None
    if trend is None:
        trend = Trend(
            platform=platform,
            external_id=it["external_id"],
            category=it["category"],
            name=it["name"],
            industry=it.get("industry"),
            url=it.get("url"),
            region=it["region"],
            source_id=it.get("source_id"),
        )
        s.add(trend)
        s.commit()
        s.refresh(trend)
    elif it.get("source_id") and not trend.source_id:
        # baris lama ke-scrape sebelum id numerik ikut diambil -> lengkapi
        trend.source_id = it["source_id"]
        s.add(trend)
        s.commit()

    period = it.get("period", 7)
    snap = s.exec(
        select(Snapshot).where(
            Snapshot.trend_id == trend.id,
            Snapshot.captured_on == today,
            Snapshot.period == period,
        )
    ).first()
    if snap is None:
        snap = Snapshot(trend_id=trend.id, captured_on=today, period=period)
    snap.views = it.get("views")
    snap.video_count = it.get("posts")
    snap.rank = it.get("rank")
    s.add(snap)
    s.commit()
    return is_new


def run_pipeline(
    categories: tuple[str, ...] | None = None,
    periods: tuple[int, ...] = (7, 30, 90),
    industries: tuple[str, ...] | None = None,
    region: str | None = None,
    platform: str = DEFAULT_PLATFORM,
    details: int = 0,
) -> dict:
    """`details` = berapa tren teratas yang kurvanya ikut ditarik setelah sapuan.

    0 = lewati (kurva ditarik manual per tren dari halaman detailnya).
    """
    init_db()
    plat = get_platform(platform)
    scraper = get_scraper(platform)
    categories = categories or plat.categories
    industries = industries or plat.industries
    new_trends = 0
    snaps = 0
    failed = 0
    out_curves: dict | None = None
    today = date.today()

    with Session(engine) as s:
        for category in categories:
            if settings.parallel_tabs > 1 and plat.key == "tiktok":
                items = fetch_many_parallel(
                    category=category,
                    periods=periods,
                    industries=industries,
                    region=region,
                )
            else:
                items = scraper.fetch_many(
                    category=category,
                    periods=periods,
                    industries=industries,
                    region=region,
                )
            for it in items:
                try:
                    if _save(s, plat.key, it, today):
                        new_trends += 1
                    snaps += 1
                except Exception as e:  # noqa: BLE001
                    s.rollback()
                    failed += 1
                    if failed <= 5:  # contoh secukupnya, jangan banjirin log
                        print(
                            f"[warn] gagal simpan {it.get('external_id')}: "
                            f"{type(e).__name__}: {str(e)[:120]}"
                        )

        # kurva ditarik SETELAH semua baris tersimpan, biar kalau bagian ini
        # gagal/dihentikan, hasil sapuan utamanya tetap aman
        if details:
            from app.detail import sync_many  # lokal: hindari impor melingkar

            try:
                # only_missing=False: kurva yang sudah ada ikut disegarkan, bukan
                # cuma yang kosong. Tanpa ini kurva lama membeku selamanya —
                # nilainya indeks relatif yang bergeser tiap hari.
                curves = sync_many(
                    s,
                    limit=details,
                    period=periods[0],
                    platform=plat.key,
                    only_missing=False,
                )
                print("[detail]", curves)
                out_curves = curves
            except Exception as e:  # noqa: BLE001
                print(f"[warn] tarik kurva gagal: {type(e).__name__}: {e}")

    out = {"new_trends": new_trends, "snapshots": snaps, "platform": plat.key}
    if out_curves:
        out["kurva"] = f"{out_curves['saved']} tren, {out_curves['points']} titik"
    if failed:
        out["failed"] = failed
        print(f"[warn] {failed} baris gagal disimpan (sisanya tetap tersimpan)")
    return out


if __name__ == "__main__":
    print(run_pipeline())
