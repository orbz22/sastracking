"""Satu run harian: scrape -> simpan Trend + Snapshot -> hitung metrik. Diisi M2/M3."""

from app.scrapers.creative_center import CreativeCenterScraper


def run_pipeline() -> None:
    scraper = CreativeCenterScraper()
    # M2: upsert Trend, insert Snapshot harian
    # M3: hitung metrik + flag viral
    raise NotImplementedError("M2/M3")
