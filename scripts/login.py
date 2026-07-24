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

LOGIN_URL = "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag?region=ID&period=7"


def main() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            settings.profile_dir,
            channel="chrome",
            headless=False,
            locale="en-US",
            viewport={"width": 1366, "height": 1000},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("\n>>> Login di jendela Chrome. Kalau sudah masuk, tekan ENTER di sini...")
        input()
        ctx.close()
        print("Sesi tersimpan di", settings.profile_dir, "- scraper berikutnya otomatis login.")


if __name__ == "__main__":
    main()
