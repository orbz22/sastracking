import re
from datetime import date

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
            ids = self._row_source_ids(page)
            for r in self._parse_hashtags(
                page.inner_text("body"), region, period, industry
            ):
                r["source_id"] = ids.get(r["external_id"])
                prev = seen.setdefault(r["external_id"], r)
                # baris bisa muncul lagi di ronde lain dgn link sudah ter-render
                if prev.get("source_id") is None and r.get("source_id"):
                    prev["source_id"] = r["source_id"]

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

    DETAIL_URL = "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag/{id}"

    def fetch_detail(
        self, source_id: str, region: str | None = None, period: int = 7
    ) -> dict:
        """Ambil isi halaman detail satu hashtag.

        Yang bisa diambil: kurva "Interest over time", daftar industri (bisa lebih
        dari satu), posts/views, dan top regions.

        Kurvanya digambar ke <canvas>, jadi TIDAK ada di DOM dan tidak lewat XHR —
        satu-satunya jalan adalah menyapu kursor di atas kanvas dan membaca
        tooltip yang muncul. Lambat (~15 detik) dan rapuh terhadap perubahan
        layout, karena itu dipanggil on-demand per hashtag, bukan di sapuan massal.
        """
        region = region or settings.region
        url = f"{self.DETAIL_URL.format(id=source_id)}?region={region}&period={period}"
        with sync_playwright() as p:
            ctx = open_context(p, self.headless)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_function(
                    "() => /#\\w/.test(document.body.innerText)", timeout=30_000
                )
            except Exception:
                pass
            page.wait_for_timeout(6_000)
            data = self._parse_detail(page, region, period)
            data["interest"] = self._sweep_chart(page)
            ctx.close()
        return data

    def fetch_details_many(
        self,
        source_ids: list[str],
        region: str | None = None,
        period: int = 7,
        on_progress=None,
    ) -> dict[str, dict]:
        """Ambil detail banyak hashtag dalam SATU browser.

        fetch_detail() membuka-tutup browser tiap panggilan (~6 detik terbuang
        per tren). Untuk puluhan/ratusan tren, biaya itu dominan — di sini
        browser dipakai ulang, tinggal ganti halaman.
        """
        region = region or settings.region
        out: dict[str, dict] = {}
        with sync_playwright() as p:
            ctx = open_context(p, self.headless)
            page = ctx.new_page()
            for i, sid in enumerate(source_ids, 1):
                url = f"{self.DETAIL_URL.format(id=sid)}?region={region}&period={period}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    try:
                        page.wait_for_function(
                            "() => /#\\w/.test(document.body.innerText)", timeout=20_000
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(3_500)
                    data = self._parse_detail(page, region, period)
                    data["interest"] = self._sweep_chart(page)
                    out[sid] = data
                except Exception as e:  # satu gagal jangan hentikan sisanya
                    print(f"[warn] detail {sid} gagal: {type(e).__name__}: {str(e)[:80]}")
                if on_progress:
                    on_progress(i, len(source_ids), sid)
            ctx.close()
        return out

    @staticmethod
    def _parse_detail(page, region: str, period: int) -> dict:
        lines = [ln.strip() for ln in page.inner_text("body").split("\n") if ln.strip()]
        name = next((ln for ln in lines if ln.startswith("#")), None)

        posts = views = None
        for k, ln in enumerate(lines):
            if ln == "Posts" and k + 1 < len(lines):
                posts = _num(lines[k + 1])
            elif ln == "Views" and k + 1 < len(lines):
                views = _num(lines[k + 1])

        # industri = baris antara nama hashtag dan tombol "Copy link"
        industries: list[str] = []
        if name in lines:
            for ln in lines[lines.index(name) + 1 :]:
                if ln in ("Copy link", "Insights"):
                    break
                industries.append(ln)

        return {
            "name": name,
            "region": region,
            "period": period,
            "posts": posts,
            "views": views,
            "industries": industries,
        }

    @staticmethod
    def _sweep_chart(page, steps: int = 40) -> list[dict]:
        """Sapu kursor di atas kanvas kurva, baca tooltip tiap langkah.

        Tooltip formatnya "26/07/26\\n26/07/26\\n90.8" (tanggal diulang + nilai).
        Nilai = indeks 0-100 relatif puncak kurva, BUKAN views.
        """
        try:
            box = page.locator("canvas").first.bounding_box()
        except Exception:
            return []
        if not box:
            return []

        found: dict[str, float] = {}
        for i in range(steps):
            frac = (i + 0.5) / steps
            try:
                page.mouse.move(
                    box["x"] + box["width"] * frac, box["y"] + box["height"] * 0.5
                )
                page.wait_for_timeout(160)
                tips = page.evaluate(
                    "() => [...document.querySelectorAll('[class*=tooltip],"
                    "[class*=Tooltip],[role=tooltip]')]"
                    ".map(e => e.innerText.trim()).filter(Boolean)"
                )
            except Exception:
                continue
            if not tips:
                continue
            parts = [x.strip() for x in tips[0].split("\n") if x.strip()]
            if len(parts) < 2:
                continue
            day, raw = parts[0], parts[-1]
            try:
                found[day] = float(raw.replace(",", ""))
            except ValueError:
                continue

        out = []
        for day, value in found.items():
            try:  # sumber pakai DD/MM/YY
                d, m, y = (int(x) for x in day.split("/"))
                out.append({"date": date(2000 + y, m, d), "value": value})
            except (ValueError, TypeError):
                continue
        return sorted(out, key=lambda x: x["date"])

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

    # Pasangkan nama hashtag <-> id numerik sumber. Naik dari tiap <a> detail ke
    # elemen leluhur yang memuat teks barisnya, jadi pasangannya ikut DOM — bukan
    # menebak lewat urutan (list-nya ter-virtualisasi, urutan tidak bisa dipercaya).
    _JS_ROW_IDS = """
    () => {
      const out = {};
      for (const a of document.querySelectorAll('a')) {
        const href = a.getAttribute('href') || '';
        const m = href.match(/trends\\/hashtag\\/(\\d+)/);
        if (!m) continue;
        let el = a, name = null;
        for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
          const t = (el.innerText || '').trim();
          const hit = t.match(/#[^\\s\\n]+/);
          if (hit) { name = hit[0]; break; }
        }
        if (name) out[name.replace(/^#/, '')] = m[1];
      }
      return out;
    }
    """

    @classmethod
    def _row_source_ids(cls, page) -> dict[str, str]:
        try:
            return page.evaluate(cls._JS_ROW_IDS) or {}
        except Exception:
            return {}

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
