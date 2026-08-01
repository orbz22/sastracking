from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

# pastikan folder data/ ada sebelum SQLite bikin file
Path("data").mkdir(exist_ok=True)

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


# Kolom yang ditambahkan setelah tabel pernah dibuat. create_all() TIDAK
# mengubah tabel yang sudah ada, jadi kolom baru harus ditambal manual — kalau
# tidak, data lama harus dibuang tiap kali skema berubah.
_MIGRATIONS: list[tuple[str, str, str]] = [
    # (tabel, kolom, definisi SQL)
    ("trend", "platform", "VARCHAR DEFAULT 'tiktok'"),
]


def _apply_migrations() -> None:
    """Tambah kolom yang belum ada. Aman dijalankan berulang."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in _MIGRATIONS:
            if table not in tables:
                continue  # tabel baru -> create_all sudah bikin lengkap
            if column in {c["name"] for c in insp.get_columns(table)}:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"[db] kolom {table}.{column} ditambahkan")


def init_db() -> None:
    """Bikin semua tabel + tambal kolom baru. Import models supaya ke-register."""
    import app.models  # noqa: F401

    _apply_migrations()
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
