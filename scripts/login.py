"""Login TikTok sekali -> sesi ke-simpan di profil Playwright (persist).

Jalanin sekali:  .venv\\Scripts\\python.exe -m scripts.login

Jendela Chrome kebuka. Klik "Log in" di kanan atas, masuk pakai akun TikTok
(atau TikTok Business). Setelah dashboard tren muncul dengan tombol "View more"
yang bisa diklik, balik ke terminal ini dan tekan ENTER. Sesi tersimpan;
scraper berikutnya otomatis login (dapat >3 baris).

Password TIDAK lewat kode ini — kamu ketik langsung di halaman TikTok.
"""

from playwright.sync_api import sync_playwright

from app.config import settings
from app.scrapers.creative_center import open_context

LOGIN_URL = "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag?region=ID&period=7"


def main() -> None:
    with sync_playwright() as p:
        ctx = open_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("\n>>> Login di jendela Chrome (JANGAN pakai 'Continue with Google').")
        print(">>> Kalau habis login kena 404, biarin saja — tekan ENTER di sini...")
        input()

        # Habis login TikTok sering redirect ke path lama (404). Balikin sendiri ke
        # URL yang benar, lalu cek beneran login atau nggak — jangan cuma nebak.
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(4_000)
            rows = page.locator("text=See analytics").count()
            anon = page.get_by_text("Log in", exact=True).count() > 0
        except Exception as exc:  # noqa: BLE001
            rows, anon = 0, True
            print("Gagal cek halaman:", exc)

        ctx.close()

        if anon or rows == 0:
            print("\n[BELUM LOGIN] Halaman masih nampilin tombol 'Log in'"
                  f" (baris tren kebaca: {rows}).")
            print("Coba lagi: .venv\\Scripts\\python.exe -m scripts.login")
        else:
            print(f"\n[OK] Login kebaca — {rows} baris tren kelihatan tanpa modal.")
            print("Sesi tersimpan di", settings.profile_dir,
                  "- scraper berikutnya otomatis login.")


if __name__ == "__main__":
    main()
