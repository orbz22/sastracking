from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

# pastikan folder data/ ada sebelum SQLite bikin file
Path("data").mkdir(exist_ok=True)

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Bikin semua tabel. Import models supaya ke-register di metadata."""
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
