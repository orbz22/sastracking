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


async def _select_industry(page, industry: str) -> None:
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(800)
        if await page.locator("[role='dialog'], .byted-modal").count():
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        sel = page.locator(".cc-select").first
        await sel.scroll_into_view_if_needed(timeout=5_000)
        await page.wait_for_timeout(300)
        await sel.click(timeout=6_000)
        await page.wait_for_timeout(800)
        await page.locator(
            ".byted-select-option-inner-wrapper", has_text=industry
        ).first.click(timeout=6_000)
        await page.wait_for_timeout(3_500)
    except Exception as e:
        print(f"[warn] pilih industri '{industry}' gagal: {str(e)[:70]}")


async def _collect_rows(
    page, region: str, period: int, industry: str | None, stale_limit: int = 6
) -> list[dict]:
    """Padanan async dari CreativeCenterScraper._scroll_collect."""
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

    stale = 0
    for _ in range(settings.scroll_max_rounds):
        await grab()
        before = len(seen)
        await page.mouse.wheel(0, 2_200)
        await page.wait_for_timeout(1_400)
        await grab()
        if await page.locator("[role='dialog'], .byted-modal, .login-modal").count():
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(600)
            break
        stale = 0 if len(seen) > before else stale + 1
        if stale >= stale_limit:
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
                await page.wait_for_timeout(2_500)
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
    for i in range(steps):
        frac = (i + 0.5) / steps
        try:
            await page.mouse.move(
                box["x"] + box["width"] * frac, box["y"] + box["height"] * 0.5
            )
            await page.wait_for_timeout(160)
            tips = await page.evaluate(
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
            await _wait_rows(page, timeout=20_000)
            await page.wait_for_timeout(3_500)
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
