"""Back up existing SQLite data before applying pending migrations."""
from pathlib import Path
import sqlite3
import time

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from clueshelf.database import database_url
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def upgrade():
    config = Config(str(ROOT / "backend/alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    path = Path(make_url(database_url()).database).resolve()
    if path.exists():
        with sqlite3.connect(path) as source:
            table = source.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone()
            current = source.execute("SELECT version_num FROM alembic_version").fetchone() if table else None
            if not current or current[0] != head:
                backup_dir = ROOT / "data/backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                target = backup_dir / f"before-migration-{time.time_ns()}.db"
                with sqlite3.connect(target) as dest:
                    source.backup(dest)
                print(f"Saved pre-migration SQLite backup: {target}", flush=True)
    command.upgrade(config, "head")
    from clueshelf.database import make_engine, session_factory
    from clueshelf.models import Save
    from clueshelf.search import sync_save
    from sqlalchemy import select
    engine = make_engine(database_url())
    with session_factory(engine)() as session:
        for save in session.scalars(select(Save)):
            sync_save(session, save)
        session.commit()
    engine.dispose()


if __name__ == "__main__":
    upgrade()
