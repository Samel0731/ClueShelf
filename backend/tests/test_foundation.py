import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from clueshelf.api import create_app
from clueshelf.database import Base, make_engine, session_factory
from clueshelf.links import parse_link
from clueshelf.models import Job, Save
from clueshelf.service import create_save
from clueshelf.worker import claim, finish, run_once


@pytest.fixture
def system(tmp_path, monkeypatch):
    from clueshelf.extraction import ExtractionResult
    from clueshelf.ai import AIUnavailable
    monkeypatch.setattr("clueshelf.worker.extract", lambda *args: ExtractionResult(status="blocked", reason="fixture: public page unavailable"))
    def unavailable(*args):
        raise AIUnavailable("fixture: model offline")
    monkeypatch.setattr("clueshelf.worker.analyze", unavailable)
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with TestClient(create_app(factory)) as client:
        yield client, factory
    engine.dispose()


URL = "https://youtu.be/abcdefghijk?si=tracking"


def add(client, **fields):
    response = client.post("/api/v1/saves", json={"url": URL, **fields})
    assert response.status_code == 201, response.text
    return response.json()["save"]


def test_save_dedup_edit_and_restart(system):
    client, factory = system
    save = add(client)
    assert save["status"] == "queued"
    duplicate = client.post("/api/v1/saves", json={"url": "https://www.youtube.com/shorts/abcdefghijk", "title": "must not overwrite"}).json()
    assert duplicate["duplicate"] and duplicate["save"]["id"] == save["id"]
    assert duplicate["save"]["title"] == ""
    assert run_once(factory)
    assert client.get(f"/api/v1/saves/{save['id']}").json()["status"] == "needs_text"
    updated = client.patch(f"/api/v1/saves/{save['id']}", json={"version": 1, "title": "京都ラーメン", "author_text": "作者介紹京都拉麵"})
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert run_once(factory)
    with TestClient(create_app(factory)) as restarted:
        restored = restarted.get(f"/api/v1/saves/{save['id']}").json()
        assert restored["status"] == "ready"
        assert restored["author_text"] == "作者介紹京都拉麵"
        assert restored["job"]["state"] == "done"
    assert client.patch(f"/api/v1/saves/{save['id']}", json={"version": 1, "title": "stale"}).status_code == 409


def test_old_job_cannot_overwrite_edit(system):
    client, factory = system
    save = add(client)
    old = claim(factory)
    assert old is not None
    assert client.patch(f"/api/v1/saves/{save['id']}", json={"version": 1, "author_text": "人工更新"}).status_code == 200
    finish(factory, old)
    assert client.get(f"/api/v1/saves/{save['id']}").json()["status"] == "queued"
    run_once(factory)
    result = client.get(f"/api/v1/saves/{save['id']}").json()
    assert result["status"] == "ready" and result["author_text"] == "人工更新"


def test_reclaimed_lease_rejects_old_token_and_exhausts(system):
    client, factory = system
    save = add(client)
    now = time.time() + 1
    first = claim(factory, now)
    second = claim(factory, now + 61)
    assert second.attempts == 2 and second.token != first.token
    finish(factory, first)
    assert client.get(f"/api/v1/saves/{save['id']}").json()["job"]["state"] == "running"
    third = claim(factory, now + 122)
    assert third.attempts == 3
    assert claim(factory, now + 183) is None
    result = client.get(f"/api/v1/saves/{save['id']}").json()
    assert result["status"] == "failed"
    retried = client.post(f"/api/v1/saves/{save['id']}/retry", json={"version": 1})
    assert retried.status_code == 200 and retried.json()["job"]["attempts"] == 0


def test_delete_while_job_running(system):
    client, factory = system
    save = add(client)
    job = claim(factory)
    assert client.delete(f"/api/v1/saves/{save['id']}?version=2").status_code == 409
    assert client.delete(f"/api/v1/saves/{save['id']}?version=1").status_code == 204
    finish(factory, job)
    assert client.get("/api/v1/saves").json() == []
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 0


def test_concurrent_duplicates(system):
    _, factory = system

    def insert(_):
        with factory() as s:
            save, _ = create_save(s, URL, "", "")
            return save.id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(insert, range(8)))
    assert len(set(ids)) == 1
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.parametrize("url", ["http://youtu.be/abcdefghijk", "https://youtube.com.evil.test/watch?v=abcdefghijk", "https://localhost/", "https://www.instagram.com/accounts/login", "https://user:pass@youtu.be/abcdefghijk", "https://youtu.be/short", "https://www.youtube.com/watch?v=abcdefghijk&v=ABCDEFGHIJK", "https://youtu.be:bad/abcdefghijk"])
def test_invalid_links(url):
    with pytest.raises(ValueError):
        parse_link(url)


@pytest.mark.parametrize("first,second", [("https://www.instagram.com/reel/ABC123/?igsh=tracking", "https://instagram.com/p/ABC123/"), ("https://www.threads.net/@someone/post/ABC123", "https://threads.com/@someone/post/ABC123?x=y")])
def test_platform_identity(first, second):
    assert parse_link(first)[:2] == parse_link(second)[:2]


def test_boundary_and_owner_isolation(system):
    client, factory = system
    assert client.post("/api/v1/saves", json={"url": URL}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/saves", json={"url": URL, "owner_id": "other"}).status_code == 422
    save = add(client)
    with factory() as s:
        item = s.get(Save, save["id"])
        item.owner_id = "other"
        s.commit()
    assert client.get("/api/v1/saves").json() == []
    assert client.get(f"/api/v1/saves/{save['id']}").status_code == 404


def test_retryable_error(system):
    client, factory = system
    save = add(client)
    job = claim(factory)
    finish(factory, job, error="temporary")
    result = client.get(f"/api/v1/saves/{save['id']}").json()
    assert result["status"] == "queued" and result["job"]["error"] == "temporary"
