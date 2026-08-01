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

# Seluruh industri yang bisa dipilih di dropdown Creative Center
# (dibaca langsung dari halaman 2026-08-02, opsi "All" tidak dihitung).
ALL_INDUSTRIES = (
    "Food & Beverage",
    "Beauty & Personal Care",
    "Apparel & Accessories",
    "News & Entertainment",
    "Games",
    "Sports & Outdoor",
    "Health",
    "Travel",
    "Education",
    "Tech & Electronics",
    "Vehicle & Transportation",
    "Baby, Kids & Maternity",
    "Household Products",
    "Home Improvement",
    "Pets",
)

# Subset lama waktu produk masih dikunci di vertikal F&B. Dipertahankan buat
# sapuan cepat/hemat waktu, bukan lagi default.
FNB_ADJACENT = (
    "Food & Beverage",
    "Health",
    "News & Entertainment",
    "Sports & Outdoor",
    "Travel",
    "Household Products",
)

_NUM_RE = re.compile(r"([\d.]+)\s*([KMB]?)", re.I)
_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


# Sembunyikan sinyal automasi (biar login pihak-ketiga spt Google ga langsung blok).
STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def browser_args() -> list[str]:
    """Args Chrome: anti-deteksi automasi + pilih profil (kalau Chrome asli)."""
    args = ["--disable-blink-features=AutomationControlled"]
    if settings.profile_subdir:
        args.append(f"--profile-directory={settings.profile_subdir}")
    return args


def open_context(p, headless: bool):
    """Buka persistent context dgn anti-deteksi automasi. Dipakai scraper + login."""
    ctx = p.chromium.launch_persistent_context(
        settings.profile_dir,
        channel="chrome",
        headless=headless,
        locale="en-US",
        viewport={"width": 1366, "height": 1400},
        args=browser_args(),
        ignore_default_args=["--enable-automation"],
    )
    ctx.add_init_script(STEALTH_JS)
    return ctx


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

    Tanpa login: ~3 baris per kombinasi, dibatasi modal "Log in or sign up".
    Sudah login (lihat scripts/login.py): tombol "View more" HILANG — halaman
    ganti jadi infinite scroll dengan list ter-virtualisasi, dan berhenti di
    ~100 baris per kombinasi. Diukur 2026-08-02: 100 baris / ~27 detik.

    Konsekuensi virtualisasi: baris yang sudah dilewati di-unmount dari DOM,
    jadi inner_text() sekali di akhir cuma nangkap yang lagi kelihatan.
    Makanya parsing dilakukan SAMBIL scroll, bukan sesudahnya.
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
            # persistent context (stealth) = sesi login ke-persist (login sekali via
            # scripts/login.py). Anon: top 3. Login: 'View more' kebuka -> lebih banyak.
            ctx = open_context(p, self.headless)
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
            rows = self._scroll_collect(page, region, period, industry)
            ctx.close()

        return rows

    def _scroll_collect(
        self,
        page,
        region: str,
        period: int,
        industry: str | None,
        max_rounds: int | None = None,
        stale_limit: int = 6,
    ) -> list[dict]:
        """Scroll pelan sambil parsing tiap ronde, dedup per external_id.

        List-nya ter-virtualisasi: baris yang lewat viewport dihapus dari DOM.
        Jadi bukan "scroll sampai habis lalu baca", tapi "baca tiap ronde".
        Berhenti kalau `stale_limit` ronde berturut-turut nggak nambah baris
        baru (bukan sekali gagal — pemuatan kadang telat satu ronde).
        """
        max_rounds = max_rounds or settings.scroll_max_rounds
        seen: dict[str, dict] = {}

        def grab() -> None:
            for r in self._parse_hashtags(
                page.inner_text("body"), region, period, industry
            ):
                seen.setdefault(r["external_id"], r)

        stale = 0
        for _ in range(max_rounds):
            grab()
            before = len(seen)
            page.mouse.wheel(0, 2_200)
            page.wait_for_timeout(1_400)
            grab()

            # dinding login (anon / sesi habis) -> tutup modal, hentikan
            if page.locator("[role='dialog'], .byted-modal, .login-modal").count():
                page.keyboard.press("Escape")
                page.wait_for_timeout(600)
                break

            stale = 0 if len(seen) > before else stale + 1
            if stale >= stale_limit:
                break
        return list(seen.values())

    def fetch_many(
        self,
        category: str = "hashtag",
        periods: tuple[int, ...] = (7, 30, 90),
        industries: tuple[str, ...] = FNB_ADJACENT,
        region: str | None = None,
    ) -> list[dict]:
        """Sapu banyak kombinasi (periode × industri) dalam SATU browser.

        Jauh lebih cepat dari memanggil fetch_trends berulang (yang membuka
        browser tiap kali). Hasil di-dedup per (external_id, period).
        """
        region = region or settings.region
        if category not in CATEGORY_URL:
            raise ValueError(f"kategori belum didukung: {category}")

        seen: dict[tuple[str, int], dict] = {}
        with sync_playwright() as p:
            ctx = open_context(p, self.headless)
            page = ctx.new_page()
            for period in periods:
                url = f"{CATEGORY_URL[category]}?region={region}&period={period}"
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_function(
                        "() => /#\\w/.test(document.body.innerText)", timeout=30_000
                    )
                except Exception:
                    pass
                page.wait_for_timeout(2_500)
                for industry in industries:
                    self._select_industry(page, industry)
                    rows = self._scroll_collect(page, region, period, industry)
                    for r in rows:
                        seen.setdefault((r["external_id"], period), r)
                    print(
                        f"  [{period:>2}h] {industry:<22} +{len(rows)} "
                        f"(total unik {len(seen)})"
                    )
            ctx.close()
        return list(seen.values())

    @staticmethod
    def _select_industry(page, industry: str) -> None:
        """Buka dropdown industri (.cc-select pertama) lalu pilih label industri.

        Wajib balik ke atas dulu: setelah _scroll_collect halaman ada di dasar
        dan dropdown keluar viewport sehingga klik timeout.
        """
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(800)
            # tutup modal/dropdown sisa dari langkah sebelumnya
            if page.locator("[role='dialog'], .byted-modal").count():
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            sel = page.locator(".cc-select").first
            sel.scroll_into_view_if_needed(timeout=5_000)
            page.wait_for_timeout(300)
            sel.click(timeout=6_000)
            page.wait_for_timeout(800)
            page.locator(
                ".byted-select-option-inner-wrapper", has_text=industry
            ).first.click(timeout=6_000)
            page.wait_for_timeout(3_500)  # tunggu tabel refresh
        except Exception as e:  # gagal filter -> lanjut pakai data sebelumnya
            print(f"[warn] pilih industri '{industry}' gagal: {str(e)[:70]}")

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
