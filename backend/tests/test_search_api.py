from pathlib import Path
import time

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from clueshelf.api import create_app
from clueshelf.database import make_engine, session_factory
from clueshelf.models import Save, SearchChunk
from clueshelf.search import sync_save
from clueshelf.service import OWNER


@pytest.fixture
def app(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'api.db'}"
    monkeypatch.setenv("CLUESHELF_DATABASE_URL", url)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    engine = make_engine(url)
    factory = session_factory(engine)
    with factory() as session:
        for identity, owner in [("mine", OWNER), ("private", "other")]:
            item = Save(id=identity, owner_id=owner, platform="threads", content_id=identity, url="https://www.threads.com/@test/post/ABC123", title="餐廳推薦", author_text="日本の料理", version=1, status="ready", created_at=time.time(), updated_at=time.time(), ai_status="complete", analysis={"topics": ["餐廳"], "tags": ["棠記"], "summary": ""}, source={"comments": [{"source_id": "r", "text": "推薦棠記生魚片", "likes": 57}]})
            session.add(item)
            session.flush()
            sync_save(session, item)
        session.commit()
    with TestClient(create_app(factory)) as client:
        yield client, factory
    engine.dispose()


def test_search_filters_classification_and_restore(app):
    client, _ = app
    result = client.get("/api/v1/search", params={"q": "棠記", "mode": "keyword"}).json()
    assert len(result["results"]) == 1
    assert result["results"][0]["match_field"] == "threads_comment:r"
    edited = client.patch("/api/v1/saves/mine/classification", json={"version": 1, "topics": ["旅遊"], "tags": [" 京都 "]})
    assert edited.status_code == 200
    assert edited.json()["effective_topics"] == ["旅遊"] and edited.json()["effective_tags"] == ["京都"]
    assert client.get("/api/v1/search", params={"q": "", "topic": "餐廳"}).json()["results"] == []
    assert len(client.get("/api/v1/search", params={"q": "京都", "topic": "旅遊"}).json()["results"]) == 1
    assert client.patch("/api/v1/saves/mine/classification", json={"version": 1, "topics": []}).status_code == 409
    restored = client.patch("/api/v1/saves/mine/classification", json={"version": 2, "topics": None, "tags": None}).json()
    assert restored["effective_topics"] == ["餐廳"] and restored["effective_tags"] == ["棠記"]
    facets = client.get("/api/v1/search/facets").json()
    assert facets["topics"] == [{"name": "餐廳", "count": 1}]


def test_semantic_not_ready_falls_back_honestly(app, monkeypatch):
    client, _ = app
    monkeypatch.setattr("clueshelf.api.is_available", lambda: False)
    result = client.get("/api/v1/search", params={"q": "棠記", "mode": "semantic"}).json()
    assert result["used_mode"] == "keyword" and result["notice"]
    assert len(result["results"]) == 1


def test_delete_cleans_fts_and_private_classification_is_inaccessible(app):
    client, factory = app
    assert client.patch("/api/v1/saves/private/classification", json={"version": 1, "topics": []}).status_code == 404
    assert client.delete("/api/v1/saves/mine?version=1").status_code == 204
    assert client.get("/api/v1/search", params={"q": "棠記"}).json()["results"] == []
    with factory() as session:
        assert session.scalar(select(SearchChunk).where(SearchChunk.save_id == "mine")) is None


def test_override_survives_model_result_replacement(app):
    client, factory = app
    client.patch("/api/v1/saves/mine/classification", json={"version": 1, "topics": ["旅遊"], "tags": []})
    with factory() as session:
        save = session.get(Save, "mine")
        save.analysis = {"topics": ["音樂"], "tags": ["日文"], "summary": "新摘要"}
        sync_save(session, save)
        session.commit()
    result = client.get("/api/v1/saves/mine").json()
    assert result["effective_topics"] == ["旅遊"] and result["effective_tags"] == []


def test_deleting_canonical_indexes_retained_draft(app):
    client, factory = app
    with factory() as session:
        draft = Save(id="draft", owner_id=OWNER, platform="threads", content_id="share:ABC", url="https://www.threads.com/share/ABC/", title="草稿特殊字", author_text="保留補充", version=1, status="ready", created_at=time.time(), updated_at=time.time(), duplicate_of="mine")
        session.add(draft)
        session.flush()
        sync_save(session, draft)
        session.commit()
    assert client.get("/api/v1/search", params={"q": "草稿特殊字"}).json()["results"] == []
    assert client.delete("/api/v1/saves/mine?version=1").status_code == 204
    assert client.get("/api/v1/search", params={"q": "草稿特殊字"}).json()["results"][0]["save"]["id"] == "draft"


def test_manual_classification_during_ai_requeues_with_version_fence(app):
    client, factory = app
    from clueshelf.service import enqueue
    from clueshelf.models import Job
    with factory() as session:
        save = session.get(Save, "mine")
        save.status = "queued"
        enqueue(session, save, kind="analyze")
        session.commit()
    response = client.patch("/api/v1/saves/mine/classification", json={"version": 1, "topics": ["旅遊"], "tags": ["手動保留"]})
    assert response.status_code == 200, response.text
    assert response.json()["effective_topics"] == ["旅遊"]
    with factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.save_id == "mine").order_by(Job.version)))
        assert [(job.version, job.state) for job in jobs] == [(1, "superseded"), (2, "queued")]
        assert session.get(Save, "mine").manual_tags == ["手動保留"]
