"""Jalanin pipeline sekali (scrape -> simpan) lalu tampilkan isi DB.

Usage:  python -m scripts.run_once [platform]     # default: tiktok
"""

import sys

from sqlmodel import Session, func, select

from app.db import engine
from app.metrics import compute, mark_viral
from app.models import Snapshot, Trend
from app.pipeline import run_pipeline
from app.scrapers.registry import DEFAULT_PLATFORM


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    platform = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PLATFORM

    result = run_pipeline(periods=(7, 30, 90), region="ID", platform=platform)
    print(f"Pipeline: +{result['new_trends']} trend baru, {result['snapshots']} snapshot.\n")

    with Session(engine) as s:
        trends = s.exec(select(Trend).where(Trend.platform == platform)).all()
        total_snap = s.exec(select(func.count()).select_from(Snapshot)).one()
        print(f"DB: {len(trends)} trend ({platform}), {total_snap} snapshot total.\n")

        # is_viral bersifat relatif per kohort -> harus dihitung sekaligus buat
        # semua baris, sama seperti di dashboard. Kalau per-tren, hasilnya beda.
        rows = []
        for t in trends:
            snaps = s.exec(select(Snapshot).where(Snapshot.trend_id == t.id)).all()
            rows.append({"trend": t, "industry": t.industry, **compute(snaps)})
        mark_viral(rows)

        for m in rows:
            t = m["trend"]
            vel = f"{m['velocity']:,.0f}/hari" if m["velocity"] is not None else "n/a"
            flag = "VIRAL" if m["is_viral"] else "-"
            print(
                f"  {t.name:<24} {t.industry or '-':<22} "
                f"[{m['status']:<6} {flag:<5}] views={m['views']:,} velocity={vel} "
                f"hist={m['history_days']}d"
            )


if __name__ == "__main__":
    main()
