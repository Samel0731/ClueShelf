from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy import text

from clueshelf.database import make_engine


def test_empty_database_upgrade(tmp_path, monkeypatch):
    path = tmp_path / "migration.db"
    url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setenv("CLUESHELF_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine(url)
    assert {"saves", "jobs"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_existing_manual_content_and_jobs_survive_upgrade_and_roundtrip(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    monkeypatch.setenv("CLUESHELF_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "0001")
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO saves VALUES ('s','local-developer','youtube','abcdefghijk','https://youtu.be/abcdefghijk','人工標題','人工內文',1,'queued',1.0,1.0)"))
        c.execute(text("INSERT INTO jobs VALUES ('j','s',1,'queued',0,1.0,NULL,NULL,NULL)"))
    engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as c:
        row = c.execute(text("SELECT title,author_text,title_manual,text_manual FROM saves")).one()
        assert tuple(row) == ("人工標題", "人工內文", 1, 1)
        assert c.execute(text("SELECT kind FROM jobs")).scalar_one() == "prepare"
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()
    command.downgrade(config, "base")
    engine = make_engine(url)
    assert "saves" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = make_engine(url)
    assert "jobs" in inspect(engine).get_table_names()
    engine.dispose()
