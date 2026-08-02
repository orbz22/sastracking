from datetime import date, datetime

from sqlmodel import Field, SQLModel


class Trend(SQLModel, table=True):
    """Satu tren unik (sound / hashtag / video) yang dilacak."""

    id: int | None = Field(default=None, primary_key=True)
    # sumber tren: "tiktok" | "instagram" | "youtube" (lihat scrapers/registry.py).
    # external_id hanya unik DI DALAM satu platform -> pencarian selalu ikut platform.
    platform: str = Field(default="tiktok", index=True)
    external_id: str = Field(index=True)          # slug internal kita (nama tanpa '#')
    # id numerik milik sumber, dipakai buat buka halaman detailnya
    # (…/trends/hashtag/7652319694679343125). Baru terisi kalau baris sempat
    # ke-scrape dengan link-nya; baris lama bisa None.
    source_id: str | None = Field(default=None, index=True)
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


class InterestPoint(SQLModel, table=True):
    """Satu titik kurva "Interest over time" milik sumber.

    Beda dari Snapshot: Snapshot itu histori yang KITA bangun sendiri (satu titik
    per hari per tren, mulai dari hari kita pertama scrape). InterestPoint adalah
    histori yang SUDAH dipunya sumber — sekali ambil langsung dapat kurva ke
    belakang, jadi momentum bisa dinilai tanpa nunggu berhari-hari.

    `value` adalah INDEKS 0-100 relatif terhadap puncak kurva itu sendiri
    (mirip Google Trends), BUKAN jumlah views. Tidak bisa dibandingkan
    antar-hashtag sebagai angka absolut — hanya bentuk kurvanya yang bermakna.
    """

    id: int | None = Field(default=None, primary_key=True)
    trend_id: int = Field(foreign_key="trend.id", index=True)
    on_date: date = Field(index=True)
    value: float
    period: int = Field(default=7)       # kurva ikut jendela yang dipilih
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
