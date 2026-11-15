import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")

    return engine


def database_url():
    default = Path(__file__).resolve().parents[2] / "data" / "clueshelf.db"
    default.parent.mkdir(parents=True, exist_ok=True)
    return os.environ.get("CLUESHELF_DATABASE_URL", f"sqlite:///{default.as_posix()}")


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
