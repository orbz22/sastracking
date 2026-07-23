"""Jalanin pipeline manual sekali. Berguna buat spike M1.

Usage:  python -m scripts.run_once
"""

from app.scrapers.creative_center import CreativeCenterScraper


def main() -> None:
    scraper = CreativeCenterScraper()
    trends = scraper.fetch_trends(vertical="fnb", category="hashtag")
    print(f"Dapat {len(trends)} tren:")
    for t in trends:
        print(" -", t)


if __name__ == "__main__":
    main()
