from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Viral Trend Intelligence"
    database_url: str = "sqlite:///./data/trends.db"
    region: str = "ID"          # target negara (Indonesia)
    vertical: str = "fnb"       # vertikal awal (F&B)
    request_timeout: int = 20   # detik, buat httpx
    profile_dir: str = ".pw-profile"  # sesi login Playwright (persist) — gitignore
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )


settings = Settings()
