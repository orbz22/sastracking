"""Jalanin scraper manual sekali. Spike M1.

Usage:  python -m scripts.run_once
"""

import sys

from app.scrapers.creative_center import CreativeCenterScraper


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    scraper = CreativeCenterScraper()  # headed (headless diblok TikTok)
    trends = scraper.fetch_trends(category="hashtag", period=7, region="ID")
    print(f"Dapat {len(trends)} tren hashtag F&B/ID:\n")
    for x in trends:
        print(
            f"  #{x['rank']:>2} {x['name']:<24} {x['industry']:<24} "
            f"posts={x['posts']:,} views={x['views']:,}"
        )
    if not trends:
        print("  (kosong — cek koneksi / TikTok ubah struktur DOM)")


if __name__ == "__main__":
    main()
