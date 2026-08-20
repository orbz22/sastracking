"""Versi paralel: banyak tab dalam satu browser.

Kenapa async, bukan thread: Playwright sync API mengikat objeknya ke thread
pembuatnya, jadi menggerakkan beberapa tab dari beberapa thread tidak aman.
Async memberi konkurensi nyata dalam satu thread.

Kenapa satu browser, bukan beberapa proses: context persistent mengunci folder
profil (`.pw-profile`), jadi proses kedua akan gagal membukanya. Satu browser,
banyak tab.

Jebakan utama: Chrome menidurkan tab yang tidak terlihat — timer dilambatkan dan
kanvas berhenti digambar ulang. Scroll di tab background jadi tidak memuat baris
baru, dan tooltip kurva tidak muncul. Karena itu flag anti-throttle di
`PARALLEL_ARGS` WAJIB ada; tanpa itu hasil tab background akan kosong senyap.
"""

import asyncio

from playwright.async_api import async_playwright

from app.config import settings
from app.scrapers.creative_center import (
    CATEGORY_URL,
    STEALTH_JS,
    CreativeCenterScraper,
    _num,
    browser_args,
)

# Tanpa ini, tab yang tidak aktif berhenti bekerja dan hasilnya kosong.
PARALLEL_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]

_S = CreativeCenterScraper  # cuma dipakai buat helper parsing statisnya


async def _open(p, headless: bool):
    ctx = await p.chromium.launch_persistent_context(
        settings.profile_dir,
        channel="chrome",
        headless=headless,
        locale="en-US",
        viewport={"width": 1366, "height": 1400},
        args=browser_args() + PARALLEL_ARGS,
        ignore_default_args=["--enable-automation"],
    )
    await ctx.add_init_script(STEALTH_JS)
    return ctx


async def _wait_rows(page, timeout: int = 30_000) -> None:
    try:
        await page.wait_for_function(
            "() => /#\\w/.test(document.body.innerText)", timeout=timeout
        )
    except Exception:
        pass


# Sidik jari keadaan daftar. Dipakai sebagai pengganti `wait_for_timeout` buta:
# daripada tidur 1,4 detik tiap ronde, kita tunggu sampai nilainya benar-benar
# berubah. Jumlah baris saja tidak cukup — daftarnya virtual, baris yang lewat
# dilepas dari DOM sehingga jumlahnya nyaris tetap. Makanya scrollHeight,
# scrollY dan href baris terakhir ikut dihitung.
_JS_FINGERPRINT = """() => {
  const a = [...document.querySelectorAll('a[href*="trends/hashtag/"]')];
  return [document.documentElement.scrollHeight, Math.round(window.scrollY),
          a.length, a.length ? a[a.length - 1].getAttribute('href') : ''].join('|');
}"""


async def _mark(page) -> str:
    try:
        return await page.evaluate(_JS_FINGERPRINT)
    except Exception:
        return ""


async def _changed(page, before: str, timeout: int = 1_800, step: int = 120) -> bool:
    """Tunggu daftar berubah dari `before`. True kalau berubah sebelum timeout.

    `step` kecil karena biaya terendah fungsi ini = 2 langkah; dengan 200 ms tiap
    ronde scroll kena pajak 400 ms padahal barisnya sering sudah siap di 150 ms.
    """
    waited = 0
    while waited < timeout:
        await page.wait_for_timeout(step)
        waited += step
        if await _mark(page) != before:
            await page.wait_for_timeout(step)  # satu langkah lagi: render tuntas
            return True
    return False


async def _settled(page, quiet: int = 600, timeout: int = 8_000, step: int = 200) -> None:
    """Tunggu daftar berhenti berubah — pengganti jeda tetap setelah muat/filter."""
    last: str | None = None
    calm = waited = 0
    while waited < timeout:
        now = await _mark(page)
        calm = calm + step if now == last else 0
        if last is not None and calm >= quiet:
            return
        last = now
        await page.wait_for_timeout(step)
        waited += step


async def _select_industry(page, industry: str) -> None:
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        if await page.locator("[role='dialog'], .byted-modal").count():
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        # Dropdown filter dirender belakangan, setelah baris pertama muncul.
        # Jangan menebak lewat jeda tetap — tunggu elemennya benar-benar ada,
        # kalau tidak seluruh kombinasi jatuh ke daftar tanpa filter.
        sel = page.locator(".cc-select").first
        await sel.wait_for(state="visible", timeout=20_000)
        await sel.scroll_into_view_if_needed(timeout=5_000)
        await sel.click(timeout=6_000)
        # tunggu dropdown benar-benar terbuka, bukan tidur menebak
        opt = page.locator(".byted-select-option-inner-wrapper", has_text=industry).first
        await opt.wait_for(state="visible", timeout=6_000)
        before = await _mark(page)
        await opt.click(timeout=6_000)
        # ganti filter = daftar dimuat ulang; tunggu berubah lalu tenang kembali
        await _changed(page, before, timeout=6_000)
        await _settled(page, timeout=6_000)
    except Exception as e:
        print(f"[warn] pilih industri '{industry}' gagal: {str(e)[:70]}")


async def _collect_rows(
    page, region: str, period: int, industry: str | None, stale_limit: int = 4
) -> list[dict]:
    """Padanan async dari CreativeCenterScraper._scroll_collect.

    `stale_limit` diturunkan dari 6 ke 4 karena berhentinya sekarang diputuskan
    dari sidik jari halaman, bukan tebakan waktu. Angkanya hasil ukur, bukan
    tebakan (4 kombinasi, 4 tab): 6 -> 390 baris/60 dtk, 4 -> 392 baris/51 dtk,
    2 -> 354 baris/40 dtk. Turun ke 2 memang paling cepat tapi memotong ~9%
    baris, jadi 4 adalah batas aman terakhir.
    """
    seen: dict[str, dict] = {}

    async def grab() -> None:
        try:
            ids = await page.evaluate(_S._JS_ROW_IDS) or {}
        except Exception:
            ids = {}
        text = await page.inner_text("body")
        for r in _S._parse_hashtags(text, region, period, industry):
            r["source_id"] = ids.get(r["external_id"])
            prev = seen.setdefault(r["external_id"], r)
            if prev.get("source_id") is None and r.get("source_id"):
                prev["source_id"] = r["source_id"]

    stale = dry = 0
    await grab()  # baris yang sudah terlihat sebelum scroll pertama
    for _ in range(settings.scroll_max_rounds):
        before = len(seen)
        mark = await _mark(page)
        await page.mouse.wheel(0, 2_200)
        # dulu: tidur 1,4 detik tiap ronde. Sekarang lanjut begitu barisnya
        # benar-benar berganti — biasanya ~250 ms.
        moved = await _changed(page, mark)
        await grab()
        if await page.locator("[role='dialog'], .byted-modal, .login-modal").count():
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(600)
            break
        # Dua penghitung, dua alasan berhenti yang berbeda:
        # `stale` = halaman benar-benar diam (scrollY & scrollHeight tidak
        #   bergerak) -> sudah mentok, berhenti cepat.
        # `dry` = halaman masih bergerak tapi tidak ada baris baru -> jaring
        #   pengaman supaya loop tetap berhenti kalau ada elemen lain yang
        #   membuat sidik jari berubah terus.
        stale = 0 if (len(seen) > before or moved) else stale + 1
        dry = 0 if len(seen) > before else dry + 1
        if stale >= stale_limit or dry >= 8:
            break
    return list(seen.values())


async def _worker_list(ctx, jobs: list[tuple[int, str]], category: str, region: str,
                       out: dict, lock: asyncio.Lock, tag: int) -> None:
    page = await ctx.new_page()
    current_period = None
    for period, industry in jobs:
        try:
            if period != current_period:
                url = f"{CATEGORY_URL[category]}?region={region}&period={period}"
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await _wait_rows(page)
                await _settled(page)
                current_period = period
            await _select_industry(page, industry)
            rows = await _collect_rows(page, region, period, industry)
            async with lock:
                for r in rows:
                    out.setdefault((r["external_id"], period), r)
                print(
                    f"  [tab{tag}] [{period:>2}h] {industry:<24} "
                    f"+{len(rows)} (total unik {len(out)})"
                )
        except Exception as e:
            print(f"[warn] tab{tag} {period}h/{industry} gagal: {type(e).__name__}")
            current_period = None  # paksa muat ulang di job berikutnya
    await page.close()


async def _run_list(category, periods, industries, region, workers, headless) -> list[dict]:
    combos = [(p, i) for p in periods for i in industries]
    # bagi round-robin: tiap tab kebagian periode campur, jadi beban muat
    # halaman merata dan tidak ada tab yang kebagian kerja berat semua
    buckets: list[list[tuple[int, str]]] = [[] for _ in range(workers)]
    for n, combo in enumerate(combos):
        buckets[n % workers].append(combo)

    out: dict[tuple[str, int], dict] = {}
    lock = asyncio.Lock()
    async with async_playwright() as p:
        ctx = await _open(p, headless)
        await asyncio.gather(
            *(
                _worker_list(ctx, b, category, region, out, lock, i + 1)
                for i, b in enumerate(buckets)
                if b
            )
        )
        await ctx.close()
    return list(out.values())


def fetch_many_parallel(
    category: str = "hashtag",
    periods: tuple[int, ...] = (7, 30, 90),
    industries: tuple[str, ...] = (),
    region: str | None = None,
    workers: int | None = None,
    headless: bool = False,
) -> list[dict]:
    """Sapuan list dengan beberapa tab sekaligus. Hasil sama, waktunya dibagi."""
    region = region or settings.region
    workers = max(1, workers or settings.parallel_tabs)
    return asyncio.run(
        _run_list(category, periods, industries, region, workers, headless)
    )


# ---------------------------------------------------------------- detail/kurva

_JS_TIP = (
    "() => [...document.querySelectorAll('[class*=tooltip],"
    "[class*=Tooltip],[role=tooltip]')]"
    ".map(e => e.innerText.trim()).filter(Boolean)"
)


async def _sweep_chart(page, steps: int = 40) -> list[dict]:
    """Padanan async dari CreativeCenterScraper._sweep_chart."""
    from datetime import date

    # hashtag tanpa kurva itu normal — jangan tunggu kanvas yang tidak ada
    # (default bounding_box menunggu 30 detik penuh, per hashtag)
    try:
        await page.wait_for_selector("canvas", timeout=6_000)
        box = await page.locator("canvas").first.bounding_box(timeout=3_000)
    except Exception:
        return []
    if not box:
        return []

    found: dict[str, float] = {}
    last = ""
    for i in range(steps):
        frac = (i + 0.5) / steps
        tips = None
        try:
            await page.mouse.move(
                box["x"] + box["width"] * frac, box["y"] + box["height"] * 0.5
            )
            # dulu: tidur 160 ms tiap langkah, dikali 60 langkah = ~10 detik per
            # hashtag. Sekarang lanjut begitu tooltip-nya berganti isi.
            for _ in range(6):
                await page.wait_for_timeout(50)
                tips = await page.evaluate(_JS_TIP)
                if tips and tips[0] != last:
                    break
        except Exception:
            continue
        if not tips:
            continue
        last = tips[0]
        parts = [x.strip() for x in tips[0].split("\n") if x.strip()]
        if len(parts) < 2:
            continue
        try:
            found[parts[0]] = float(parts[-1].replace(",", ""))
        except ValueError:
            continue

    out = []
    for day, value in found.items():
        try:
            d, m, y = (int(x) for x in day.split("/"))
            out.append({"date": date(2000 + y, m, d), "value": value})
        except (ValueError, TypeError):
            continue
    return sorted(out, key=lambda x: x["date"])


async def _worker_detail(ctx, ids: list[str], region: str, period: int,
                         out: dict, lock: asyncio.Lock, tag: int) -> None:
    page = await ctx.new_page()
    for sid in ids:
        url = f"{_S.DETAIL_URL.format(id=sid)}?region={region}&period={period}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            # Batas waktu di sini sengaja pendek. Sebagian hashtag halamannya
            # memang kosong (id lama/kedaluwarsa) dan tidak akan pernah merender
            # apa pun; batas yang longgar cuma membuat tiap hashtag mati memakan
            # puluhan detik. Yang berisi selalu render jauh di bawah batas ini.
            await _wait_rows(page, timeout=10_000)
            # angka Posts/Views datang belakangan setelah nama hashtag muncul;
            # tunggu itu, jangan tidur 3,5 detik menebak
            try:
                await page.wait_for_function(
                    "() => /\\bViews\\b/.test(document.body.innerText)", timeout=5_000
                )
            except Exception:
                pass
            text = await page.inner_text("body")
            data = _parse_detail_text(text, region, period)
            data["interest"] = await _sweep_chart(
                page, _S.SWEEP_STEPS.get(period, 40)
            )
            async with lock:
                out[sid] = data
                print(f"  [tab{tag}] detail {sid} -> {len(data['interest'])} titik")
        except Exception as e:
            print(f"[warn] tab{tag} detail {sid} gagal: {type(e).__name__}")
    await page.close()


def _parse_detail_text(text: str, region: str, period: int) -> dict:
    """Sama dengan _parse_detail versi sync, tapi menerima teks (bukan page)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    name = next((ln for ln in lines if ln.startswith("#")), None)
    posts = views = None
    for k, ln in enumerate(lines):
        if ln == "Posts" and k + 1 < len(lines):
            posts = _num(lines[k + 1])
        elif ln == "Views" and k + 1 < len(lines):
            views = _num(lines[k + 1])
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


async def _run_details(ids, region, period, workers, headless) -> dict[str, dict]:
    buckets: list[list[str]] = [[] for _ in range(workers)]
    for n, sid in enumerate(ids):
        buckets[n % workers].append(sid)

    out: dict[str, dict] = {}
    lock = asyncio.Lock()
    async with async_playwright() as p:
        ctx = await _open(p, headless)
        await asyncio.gather(
            *(
                _worker_detail(ctx, b, region, period, out, lock, i + 1)
                for i, b in enumerate(buckets)
                if b
            )
        )
        await ctx.close()
    return out


def fetch_details_parallel(
    source_ids: list[str],
    region: str | None = None,
    period: int = 7,
    workers: int | None = None,
    headless: bool = False,
) -> dict[str, dict]:
    """Tarik kurva banyak hashtag lewat beberapa tab sekaligus."""
    region = region or settings.region
    workers = max(1, workers or settings.parallel_tabs)
    return asyncio.run(_run_details(source_ids, region, period, workers, headless))
