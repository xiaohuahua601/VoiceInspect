from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
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
