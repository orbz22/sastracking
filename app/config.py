from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Viral Trend Intelligence"
    database_url: str = "sqlite:///./data/trends.db"
    region: str = "ID"          # target negara (Indonesia)
    platform: str = "tiktok"    # platform default (lihat scrapers/registry.py)
    # Peninggalan waktu produk masih dikunci di satu vertikal. Cakupan sekarang
    # semua industri; nilai ini cuma dipakai sebagai default filter awal.
    vertical: str = "fnb"
    request_timeout: int = 20   # detik, buat httpx
    # --- keamanan waktu dibuka ke internet (ngrok dsb) -----------------------
    # Kosong = tanpa autentikasi. Aman selama cuma didengarkan di 127.0.0.1,
    # TIDAK aman begitu di-tunnel keluar: /refresh itu POST yang menjalankan
    # Chrome memakai sesi TikTok asli pemilik mesin. Isi keduanya sebelum
    # membuka tunnel; scripts/share.ps1 menolak jalan kalau masih kosong.
    auth_user: str = ""
    auth_pass: str = ""
    # Kredensial tingkat kedua: boleh menekan tombol aksi walaupun read_only
    # menyala. Gunanya memisahkan "penonton boleh lihat" dari "saya boleh
    # update dari jauh" — tanpa ini, sandi yang dibagikan ke penonton otomatis
    # jadi sandi yang bisa menjalankan Chrome di mesin ini. Kosong = tidak ada
    # jalur tulis dari jauh sama sekali.
    admin_user: str = ""
    admin_pass: str = ""
    # True = POST ditolak untuk penonton biasa (refresh, tarik kurva). Pemegang
    # kredensial admin tetap boleh.
    read_only: bool = False
    # Sesi login Playwright. Default: profil terpisah `.pw-profile` (gitignore).
    # Buat pakai Chrome asli: set profile_dir ke folder "User Data" Chrome +
    # profile_subdir ke folder profilnya (mis. "Default" / "Profile 1").
    profile_dir: str = ".pw-profile"
    profile_subdir: str = ""  # kosong = pakai profile_dir apa adanya
    # Batas ronde scroll per kombinasi. Sudah login, TikTok mentok ~100 baris
    # (~12 ronde). 40 = ruang aman; turunin kalau refresh kelamaan.
    scroll_max_rounds: int = 40
    # Jumlah tab yang jalan barengan saat scrape. Naikin = lebih cepat tapi lebih
    # berat (tiap tab = satu renderer Chrome) dan makin mirip pola bot.
    parallel_tabs: int = 4
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )


settings = Settings()
