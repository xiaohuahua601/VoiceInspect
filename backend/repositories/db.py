from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)


if is_sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        """Make API and Worker coexist safely on the local SQLite volume."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            # Do not change journal_mode on every connection. API and Worker
            # share a Windows bind-mounted SQLite file, and concurrent WAL
            # mode changes can raise "unable to open database file" during
            # connection setup. The database keeps its existing journal mode
            # and busy_timeout still protects normal reader/writer contention.
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Path("./data/db").mkdir(parents=True, exist_ok=True)
    if not settings.auto_create_schema:
        return
    from backend.repositories import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
