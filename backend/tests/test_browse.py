from pathlib import Path
import time

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, delete

from clueshelf.database import make_engine, session_factory
from clueshelf.models import Save
from clueshelf.browse_models import BrowseSnapshot
from clueshelf.browse_api import create_router
from clueshelf import browse as explorer
from clueshelf.taxonomy import seed_defaults, resolve, create_taxon, sync_classifications
from clueshelf.taxonomy_models import Taxon, SaveTaxon
from clueshelf.search import sync_save


@pytest.fixture
def system(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'browse.db'}"
    monkeypatch.setenv("CLUESHELF_DATABASE_URL", url)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    engine = make_engine(url)
    factory = session_factory(engine)
    monkeypatch.setattr(explorer, "is_available", lambda: False)
    with factory() as session:
        seed_defaults(session)
        for n in range(75):
            item = Save(id=f"save-{n:03}", owner_id="local-developer", platform="youtube", content_id=f"video-{n}", url="https://www.youtube.com/watch?v=abcdefghijk", title=f"食譜 {n}", author_text="料理原文" * 1000, created_at=1000 if n < 40 else 900, updated_at=1000, version=1, status="ready", ai_status="complete", analysis={"summary": "摘要" * 500, "topics": ["食譜"] if n < 70 else [], "tags": ["高蛋白", "日文"] if n < 50 else []})
            session.add(item)
            session.flush()
            sync_classifications(session, item)
            sync_save(session, item)
        foreign = Save(id="foreign", owner_id="someone-else", platform="youtube", content_id="foreign", url="https://www.youtube.com/watch?v=abcdefghijk", title="private", author_text="", created_at=9999, updated_at=9999)
        session.add(foreign)
        session.commit()
    app = FastAPI()
    app.include_router(create_router(factory))
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def test_lightweight_keyset_pages_do_not_duplicate_ties_or_additions(system):
    client, factory = system
    first = client.get("/api/v1/browse").json()
    assert first["total"] == 75 and len(first["items"]) == 30
    assert len(first["items"][0]["excerpt"]) <= 220
    assert len(first["items"][0]["summary"]) <= 300
    assert "source" not in first["items"][0] and "author_text" not in first["items"][0]
    with factory() as session:
        session.add(Save(id="new", owner_id="local-developer", platform="youtube", content_id="new", url="https://youtu.be/abcdefghijk", title="new", author_text="", created_at=10000, updated_at=10000))
        session.execute(delete(Save).where(Save.id == "save-001"))
        session.commit()
    second = client.get("/api/v1/browse", params={"cursor": first["next_cursor"]}).json()
    third = client.get("/api/v1/browse", params={"cursor": second["next_cursor"]}).json()
    ids = [item["id"] for page in (first,second,third) for item in page["items"]]
    assert len(ids) == 75 and len(ids) == len(set(ids))
    assert "new" not in ids and "foreign" not in ids


def test_full_scope_facets_graph_and_expand(system):
    client, _ = system
    page = client.get("/api/v1/browse").json()
    protein = next(item for item in page["tags"] if item["name"] == "高蛋白")
    assert protein["count"] == 50  # Not just the thirty rendered cards.
    graph = client.get("/api/v1/graph", params={"snapshot_id": page["snapshot_id"]}).json()
    assert not any(node["kind"] == "save" for node in graph["nodes"])
    assert next(node for node in graph["nodes"] if node["id"] == protein["id"])["count"] == 50
    assert next(node for node in graph["nodes"] if node["id"] == "unclassified")["count"] == 5
    assert any(edge["count"] == 50 for edge in graph["edges"])
    first = client.get("/api/v1/graph/expand", params={"snapshot_id": page["snapshot_id"], "node_id": protein["id"]}).json()
    assert len(first["items"]) == 30 and first["total"] == 50
    second = client.get("/api/v1/graph/expand", params={"snapshot_id": page["snapshot_id"], "node_id": protein["id"], "cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 20 and second["next_cursor"] is None
    assert not {item["id"] for item in first["items"]}.intersection(item["id"] for item in second["items"])
    unclassified = client.get("/api/v1/graph/expand", params={"snapshot_id": page["snapshot_id"], "node_id": "unclassified"}).json()
    assert unclassified["total"] == 5


def test_filters_and_scopes_validate_ownership_and_expiry(system):
    client, factory = system
    all_items = client.get("/api/v1/browse").json()
    protein = next(item for item in all_items["tags"] if item["name"] == "高蛋白")
    filtered = client.get("/api/v1/browse", params={"tag": protein["id"]}).json()
    assert filtered["total"] == 50
    assert client.get("/api/v1/browse", params={"cursor": filtered["next_cursor"]}).status_code == 422
    assert client.get("/api/v1/browse", params={"cursor": "garbage"}).status_code == 422
    assert client.get("/api/v1/graph", params={"snapshot_id": "not-mine"}).status_code == 404
    with factory() as session:
        snapshot = session.get(BrowseSnapshot, filtered["snapshot_id"])
        snapshot.expires_at = time.time()-1
        session.commit()
    assert client.get("/api/v1/graph", params={"snapshot_id": filtered["snapshot_id"]}).status_code == 410
    assert client.get("/api/v1/browse/status", params=[("ids", "foreign"), ("ids", "save-001")]).json()["deleted_ids"] == ["foreign"]


def test_keyword_full_rank_snapshot_exceeds_old_fifty_cap(system):
    client, factory = system
    first = client.get("/api/v1/browse", params={"q": "食譜", "mode": "keyword"}).json()
    assert first["total"] == 75
    with factory() as session:
        session.execute(delete(Save).where(Save.id == first["items"][0]["id"]))
        session.commit()
    pages = [first]
    while pages[-1]["next_cursor"]:
        response = client.get("/api/v1/browse", params={"q": "食譜", "mode": "keyword", "cursor": pages[-1]["next_cursor"]})
        assert response.status_code == 200, response.text
        pages.append(response.json())
    ids = [item["id"] for page in pages for item in page["items"]]
    assert len(ids) == 75 and len(set(ids)) == 75


def test_graph_limits_and_selected_priority(system):
    client, factory = system
    with factory() as session:
        for n in range(50):
            tag = create_taxon(session, "local-developer", "tag", f"tag-{n}")
            session.flush()
            session.add(SaveTaxon(save_id="save-000", taxon_id=tag.id, origin="manual"))
        session.commit()
    page = client.get("/api/v1/browse").json()
    graph = client.get("/api/v1/graph", params={"snapshot_id": page["snapshot_id"]}).json()
    assert len([node for node in graph["nodes"] if node["kind"] == "tag"]) == 40
    assert len(graph["edges"]) <= 120
    assert graph["truncated"]["tags"] and graph["truncated"]["edges"]


def test_status_only_updates_requested_items(system):
    client, _ = system
    result = client.get("/api/v1/browse/status", params=[("ids", "save-010"), ("ids", "missing")]).json()
    assert len(result["items"]) == 1 and result["items"][0]["id"] == "save-010"
    assert result["deleted_ids"] == ["missing"] and result["total"] == 75
    assert client.get("/api/v1/browse/status", params=[("ids", str(i)) for i in range(101)]).status_code == 422


def test_cursor_shape_and_scope_statistics(system):
    client, _ = system
    first = client.get("/api/v1/browse", params={"q": "食譜", "mode": "keyword"}).json()
    forged = explorer.encode_cursor({"snapshot": first["snapshot_id"], "after": [1000, "save-010"]})
    assert client.get("/api/v1/browse", params={"q": "食譜", "mode": "keyword", "cursor": forged}).status_code == 422
    malformed = explorer.encode_cursor({"snapshot": ["bad"], "offset": 30})
    assert client.get("/api/v1/browse", params={"cursor": malformed}).status_code == 422
    counts = client.get("/api/v1/browse/facets", params={"snapshot_id": first["snapshot_id"]}).json()
    assert counts["total"] == 75 and "items" not in counts
    assert counts["topics"] == first["topics"] and counts["tags"] == first["tags"]


def test_semantic_snapshot_preserves_original_ranking(system, monkeypatch):
    client, _ = system
    monkeypatch.setattr(explorer, "index_stats", lambda *args: {"ready": 1, "pending": 0, "failed": 0, "model_ready": True})
    monkeypatch.setattr(explorer, "embed", lambda *args, **kwargs: [[1.0] * 384])
    monkeypatch.setattr(explorer, "_semantic", lambda session, ids, vector: [{"save_id": identity, "score": 1.0, "match_field": "summary", "match_text": "original ranking"} for identity in sorted(ids, reverse=True)])
    first = client.get("/api/v1/browse", params={"q": "備餐", "mode": "semantic"}).json()
    assert first["total"] == 75 and first["items"][0]["id"] == "save-074"
    def must_not_rerank(*args, **kwargs):
        raise AssertionError("Cached result must not rerank")
    monkeypatch.setattr(explorer, "_semantic", must_not_rerank)
    second = client.get("/api/v1/browse", params={"q": "備餐", "mode": "semantic", "cursor": first["next_cursor"]}).json()
    assert second["items"][0]["id"] == "save-044"
    assert all(item["match_text"] == "original ranking" for item in second["items"])
