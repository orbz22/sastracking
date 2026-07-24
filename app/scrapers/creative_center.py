import re

from playwright.sync_api import sync_playwright

from app.config import settings
from app.scrapers.base import TrendScraper

# Halaman tren per kategori (Creative Center / "TikTok One Creative Suite").
# Data dirender ke DOM (bukan JSON XHR, bukan HTML awal) -> di-scrape dari DOM.
CATEGORY_URL = {
    "hashtag": "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag",
}

_NUM_RE = re.compile(r"([\d.]+)\s*([KMB]?)", re.I)
_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _num(s: str) -> int | None:
    """'43.1K' -> 43100 ; '59.4M' -> 59400000."""
    if not s:
        return None
    m = _NUM_RE.match(s.strip().replace(",", ""))
    if not m:
        return None
    return int(float(m.group(1)) * _MULT[m.group(2).upper()])


class CreativeCenterScraper(TrendScraper):
    """UTAMA (§1b): scrape tren dari Creative Center via DOM (Playwright).

    Tanpa login: dapat top ~3 per kategori. Login (akun TikTok Business) =
    'View more' kebuka -> top 20/100. Login belum dipasang (fase berikut).
    """

    # headless=True DIBLOK TikTok (ERR_HTTP_RESPONSE_CODE_FAILURE) -> default headed.
    def __init__(self, headless: bool = False):
        self.headless = headless

    def fetch_trends(
        self,
        vertical: str = "fnb",
        category: str = "hashtag",
        period: int = 7,
        region: str | None = None,
    ) -> list[dict]:
        region = region or settings.region
        if category not in CATEGORY_URL:
            raise ValueError(f"kategori belum didukung: {category}")
        url = f"{CATEGORY_URL[category]}?region={region}&period={period}"

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=self.headless)
            page = browser.new_context(
                locale="en-US", viewport={"width": 1366, "height": 1400}
            ).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_function(
                    "() => /#\\w/.test(document.body.innerText)", timeout=30_000
                )
            except Exception:
                pass
            page.wait_for_timeout(3_000)
            text = page.inner_text("body")
            browser.close()

        return self._parse_hashtags(text, region, period)

    @staticmethod
    def _parse_hashtags(text: str, region: str, period: int) -> list[dict]:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        out: list[dict] = []
        for i, ln in enumerate(lines):
            if not ln.startswith("#"):
                continue
            name = ln
            rank = int(lines[i - 1]) if i > 0 and lines[i - 1].isdigit() else None
            industry = lines[i + 1] if i + 1 < len(lines) else None
            posts = views = None
            # pola: [#name, industry, postsval, 'Posts', viewsval, 'Views']
            if i + 3 < len(lines) and lines[i + 3] == "Posts":
                posts = _num(lines[i + 2])
            if i + 5 < len(lines) and lines[i + 5] == "Views":
                views = _num(lines[i + 4])
            slug = name.lstrip("#")
            out.append(
                {
                    "external_id": slug,
                    "category": "hashtag",
                    "name": name,
                    "industry": industry,
                    "posts": posts,
                    "views": views,
                    "rank": rank,
                    "region": region,
                    "period": period,
                    "url": f"https://www.tiktok.com/tag/{slug}",
                }
            )
        return out
