from app.scrapers.base import TrendScraper


class CreativeCenterScraper(TrendScraper):
    """UTAMA (§1b): ambil tren dari TikTok Creative Center via httpx.

    Diimplementasikan di M1. Ref struktur endpoint (pahami, jangan copy buta):
    github.com/lofe-w/tiktok-creative-center-scraper-public
    """

    def fetch_trends(self, vertical: str = "fnb", category: str = "hashtag") -> list[dict]:
        raise NotImplementedError("M1: implementasi fetch Creative Center (httpx)")
