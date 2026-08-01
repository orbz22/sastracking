"""Daftar platform + scraper-nya.

Titik colok buat sumber baru: bikin scraper yang mewarisi TrendScraper, lalu
daftarkan di sini. Sisanya (pipeline, API, dashboard) sudah platform-agnostik —
mereka cuma baca metadata di bawah, nggak pernah nyebut TikTok langsung.

Platform yang scraper-nya belum ada tetap didaftarkan dengan available=False
supaya tampil di UI sebagai "segera" — bukan disembunyikan, biar arah produknya
kelihatan dan nggak ada link mati.
"""

from dataclasses import dataclass

from app.scrapers.base import TrendScraper
from app.scrapers.creative_center import ALL_INDUSTRIES, CreativeCenterScraper


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    scraper: type[TrendScraper] | None = None
    categories: tuple[str, ...] = ("hashtag",)
    industries: tuple[str, ...] = ()
    note: str = ""

    @property
    def available(self) -> bool:
        return self.scraper is not None


PLATFORMS: dict[str, Platform] = {
    p.key: p
    for p in (
        Platform(
            key="tiktok",
            label="TikTok",
            scraper=CreativeCenterScraper,
            categories=("hashtag",),  # sound + video menyusul
            industries=ALL_INDUSTRIES,
            note="Sumber: TikTok Creative Center",
        ),
        Platform(
            key="instagram",
            label="Instagram",
            note="Belum ada sumber data resmi yang setara Creative Center",
        ),
        Platform(
            key="youtube",
            label="YouTube",
            note="Kandidat: YouTube Data API (kuota harian, butuh API key)",
        ),
    )
}

DEFAULT_PLATFORM = "tiktok"


def get_platform(key: str | None) -> Platform:
    """Ambil platform; jatuh ke default kalau key nggak dikenal."""
    return PLATFORMS.get(key or DEFAULT_PLATFORM, PLATFORMS[DEFAULT_PLATFORM])


def get_scraper(key: str | None) -> TrendScraper:
    p = get_platform(key)
    if p.scraper is None:
        raise ValueError(f"platform '{p.key}' belum punya scraper")
    return p.scraper()
