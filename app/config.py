from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Viral Trend Intelligence"
    database_url: str = "sqlite:///./data/trends.db"
    region: str = "ID"          # target negara (Indonesia)
    vertical: str = "fnb"       # vertikal awal (F&B)
    request_timeout: int = 20   # detik, buat httpx
    # Sesi login Playwright. Default: profil terpisah `.pw-profile` (gitignore).
    # Buat pakai Chrome asli: set profile_dir ke folder "User Data" Chrome +
    # profile_subdir ke folder profilnya (mis. "Default" / "Profile 1").
    profile_dir: str = ".pw-profile"
    profile_subdir: str = ""  # kosong = pakai profile_dir apa adanya
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )


settings = Settings()
