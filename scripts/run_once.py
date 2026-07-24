"""Jalanin pipeline sekali (scrape -> simpan) lalu tampilkan isi DB.

Usage:  python -m scripts.run_once
"""

import sys

from sqlmodel import Session, func, select

from app.db import engine
from app.metrics import compute
from app.models import Snapshot, Trend
from app.pipeline import run_pipeline


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    result = run_pipeline(categories=("hashtag",), periods=(7, 30, 90), region="ID")
    print(f"Pipeline: +{result['new_trends']} trend baru, {result['snapshots']} snapshot.\n")

    with Session(engine) as s:
        trends = s.exec(select(Trend)).all()
        total_snap = s.exec(select(func.count()).select_from(Snapshot)).one()
        print(f"DB: {len(trends)} trend, {total_snap} snapshot total.\n")
        for t in trends:
            snaps = s.exec(select(Snapshot).where(Snapshot.trend_id == t.id)).all()
            m = compute(snaps)
            vel = f"{m['velocity']:,.0f}/hari" if m["velocity"] is not None else "n/a"
            flag = "VIRAL" if m["is_viral"] else "-"
            print(
                f"  {t.name:<24} {t.industry or '-':<22} "
                f"[{m['status']:<6} {flag:<5}] views={m['views']:,} velocity={vel} "
                f"hist={m['history_days']}d"
            )


if __name__ == "__main__":
    main()
