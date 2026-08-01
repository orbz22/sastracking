from datetime import date, datetime

from sqlmodel import Field, SQLModel


class Trend(SQLModel, table=True):
    """Satu tren unik (sound / hashtag / video) yang dilacak."""

    id: int | None = Field(default=None, primary_key=True)
    # sumber tren: "tiktok" | "instagram" | "youtube" (lihat scrapers/registry.py).
    # external_id hanya unik DI DALAM satu platform -> pencarian selalu ikut platform.
    platform: str = Field(default="tiktok", index=True)
    external_id: str = Field(index=True)          # id dari sumber (Creative Center)
    category: str                                  # "sound" | "hashtag" | "video"
    name: str
    industry: str | None = None                    # mis. "Games", "News & Entertainment"
    url: str | None = None
    region: str = "ID"
    # (kolom `vertical` dihapus — peninggalan waktu produk masih dikunci di F&B,
    #  tidak pernah dibaca. Segmentasi sekarang lewat `industry`.)
    first_seen: datetime = Field(default_factory=datetime.utcnow)


class Snapshot(SQLModel, table=True):
    """Rekam metrik satu tren pada satu hari. Kumpulannya = histori (aset prediksi)."""

    id: int | None = Field(default=None, primary_key=True)
    trend_id: int = Field(foreign_key="trend.id", index=True)
    captured_on: date = Field(default_factory=date.today, index=True)
    # jendela waktu sumber (7/30/90 hari). Views antar-period TIDAK sebanding —
    # metrik hanya boleh dihitung dari snapshot dengan period yang sama.
    period: int = Field(default=7, index=True)
    views: int | None = None
    video_count: int | None = None
    engagement_rate: float | None = None
    rank: int | None = None
