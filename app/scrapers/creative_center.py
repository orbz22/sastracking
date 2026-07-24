import re

from playwright.sync_api import sync_playwright

from app.config import settings
from app.scrapers.base import TrendScraper

# Halaman tren per kategori (Creative Center / "TikTok One Creative Suite").
# Data dirender ke DOM (bukan JSON XHR, bukan HTML awal) -> di-scrape dari DOM.
CATEGORY_URL = {
    "hashtag": "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag",
}

# vertical internal -> label industri di dropdown Creative Center
INDUSTRY_LABEL = {
    "fnb": "Food & Beverage",
}

_NUM_RE = re.compile(r"([\d.]+)\s*([KMB]?)", re.I)
_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def browser_args() -> list[str]:
    """Args Chrome — pilih profil kalau pakai Chrome asli (multi-profil)."""
    args: list[str] = []
    if settings.profile_subdir:
        args.append(f"--profile-directory={settings.profile_subdir}")
    return args


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
        industry: str | None = None,
    ) -> list[dict]:
        region = region or settings.region
        industry = industry or INDUSTRY_LABEL.get(vertical)
        if category not in CATEGORY_URL:
            raise ValueError(f"kategori belum didukung: {category}")
        url = f"{CATEGORY_URL[category]}?region={region}&period={period}"

        with sync_playwright() as p:
            # persistent context = sesi login ke-persist (login sekali via scripts/login.py).
            # Anon: dapat top 3. Login: 'View more' kebuka -> lebih banyak.
            ctx = p.chromium.launch_persistent_context(
                settings.profile_dir,
                channel="chrome",
                headless=self.headless,
                locale="en-US",
                viewport={"width": 1366, "height": 1400},
                args=browser_args(),
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_function(
                    "() => /#\\w/.test(document.body.innerText)", timeout=30_000
                )
            except Exception:
                pass
            page.wait_for_timeout(3_000)
            if industry:
                self._select_industry(page, industry)
            self._load_more(page)
            text = page.inner_text("body")
            ctx.close()

        return self._parse_hashtags(text, region, period, industry)

    @staticmethod
    def _load_more(page, max_clicks: int = 15) -> None:
        """Klik 'View more' berulang (kalau login) sampai baris berhenti nambah."""
        for _ in range(max_clicks):
            before = page.locator("text=See analytics").count()
            vm = page.get_by_text("View more", exact=True)
            if vm.count() == 0:
                break
            try:
                vm.first.scroll_into_view_if_needed(timeout=3_000)
                vm.first.click(timeout=4_000)
            except Exception:
                break
            page.wait_for_timeout(2_500)
            if page.locator("text=See analytics").count() <= before:
                break  # anon / ga nambah -> stop

    @staticmethod
    def _select_industry(page, industry: str) -> None:
        """Buka dropdown industri (.cc-select pertama) lalu pilih label industri."""
        try:
            page.locator(".cc-select").first.click(timeout=8_000)
            page.wait_for_timeout(700)
            page.locator(
                ".byted-select-option-inner-wrapper", has_text=industry
            ).first.click(timeout=8_000)
            page.wait_for_timeout(3_500)  # tunggu tabel refresh
        except Exception as e:  # gagal filter -> lanjut pakai data "All"
            print(f"[warn] pilih industri '{industry}' gagal: {str(e)[:80]}")

    @staticmethod
    def _parse_hashtags(
        text: str, region: str, period: int, industry: str | None = None
    ) -> list[dict]:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        n = len(lines)
        markers = {"Posts", "Views", "See analytics"}
        out: list[dict] = []
        for i, ln in enumerate(lines):
            if not ln.startswith("#"):
                continue
            name = ln
            rank = int(lines[i - 1]) if i > 0 and lines[i - 1].isdigit() else None

            # window: sampai baris '#' berikutnya / 'See analytics' / maks 11 baris
            window: list[str] = []
            j = i + 1
            while j < n and j < i + 12 and not lines[j].startswith("#"):
                window.append(lines[j])
                if lines[j] == "See analytics":
                    break
                j += 1

            # industri = baris pertama yg bukan angka & bukan marker
            row_industry = None
            for w in window:
                if w in markers or w[0].isdigit():
                    continue
                row_industry = w
                break

            # posts/views = angka tepat SEBELUM marker 'Posts'/'Views'
            posts = views = None
            for k, w in enumerate(window):
                if w == "Posts" and k > 0:
                    posts = _num(window[k - 1])
                elif w == "Views" and k > 0:
                    views = _num(window[k - 1])

            slug = name.lstrip("#")
            out.append(
                {
                    "external_id": slug,
                    "category": "hashtag",
                    "name": name,
                    "industry": row_industry or industry,
                    "posts": posts,
                    "views": views,
                    "rank": rank,
                    "region": region,
                    "period": period,
                    "url": f"https://www.tiktok.com/tag/{slug}",
                }
            )
        return out
