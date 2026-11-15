import json
import time
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from clueshelf.database import Base, make_engine, session_factory
from clueshelf.models import Save
from clueshelf.taxonomy_models import Taxon, SaveTaxon, TaxonomySuggestionJob
from clueshelf.taxonomy import seed_defaults, create_taxon, resolve, sync_classifications, effective_names, validate_assignment, filter_ai_names
from clueshelf.taxonomy_api import create_router
from clueshelf.ai import analyze, topic_catalog, AIUnavailable
from clueshelf.taxonomy_suggestions import run_once


@pytest.fixture
def system(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'taxonomy.db'}")
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with factory() as session:
        seed_defaults(session)
        save = Save(id="saved", owner_id="local-developer", platform="youtube", content_id="abcdefghijk", url="https://youtu.be/abcdefghijk", title="投資與食譜", author_text="原文", created_at=time.time(), updated_at=time.time(), status="ready", ai_status="complete", analysis={"topics":["食譜"], "tags":["Recipe", "LLM"]})
        session.add(save)
        session.flush()
        sync_classifications(session, save)
        session.commit()
    app = FastAPI()
    app.include_router(create_router(factory))
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def catalog(client):
    return client.get("/api/v1/taxonomy").json()["items"]


def test_custom_topic_duplicates_owner_and_manual_validation(system):
    client, factory = system
    created = client.post("/api/v1/taxonomy", json={"kind":"topic", "name":" 投資理財 ", "description":"股票、ETF與資產配置"}).json()
    assert created["name"] == "投資理財"
    assert client.post("/api/v1/taxonomy",json={"kind":"topic","name":"投資理財"}).status_code == 409
    assert client.post("/api/v1/taxonomy",json={"kind":"tag","name":"ｌｌｍ"}).status_code == 409
    assert client.post("/api/v1/taxonomy",json={"kind":"topic","name":"  "}).status_code == 422
    with factory() as session:
        assert validate_assignment(session,"local-developer","topic",["投資理財"]) == ["投資理財"]
        with pytest.raises(ValueError): validate_assignment(session,"local-developer","topic",["未知主題"])
        other = create_taxon(session,"other","topic","私人")
        other_id = other.id
        session.commit()
    assert client.patch(f"/api/v1/taxonomy/{other_id}",json={"version":1,"name":"不可讀"}).status_code == 404


def test_rename_merge_preserves_raw_and_aliases_reindexes_membership(system):
    client, factory = system
    recipe = next(item for item in catalog(client) if item["name"] == "食譜")
    preview = client.post(f"/api/v1/taxonomy/{recipe['id']}/preview",json={"name":"料理"}).json()
    assert preview["count"] == 1 and preview["saves"][0]["id"] == "saved"
    changed = client.patch(f"/api/v1/taxonomy/{recipe['id']}",json={"version":1,"name":"料理"})
    assert changed.status_code == 200
    target = client.post("/api/v1/taxonomy",json={"kind":"topic","name":"飲食"}).json()
    merged = client.post(f"/api/v1/taxonomy/{recipe['id']}/merge",json={"version":2,"target_id":target["id"],"target_version":1})
    assert merged.status_code == 200
    with factory() as session:
        save = session.get(Save,"saved")
        assert save.analysis["topics"] == ["食譜"]
        assert effective_names(session,save,"topic") == ["飲食"]
        assert session.get(SaveTaxon,(save.id,target["id"]))
        assert not session.get(SaveTaxon,(save.id,recipe["id"]))
        assert resolve(session,save.owner_id,"topic","食譜").id == target["id"]
    assert client.post("/api/v1/taxonomy",json={"kind":"topic","name":"食譜"}).status_code == 409
    # A merged source's old name can become its canonical target's new display name.
    assert client.patch(f"/api/v1/taxonomy/{target['id']}",json={"version":2,"name":"食譜"}).status_code == 200


def test_archive_keeps_existing_but_rejects_new_ai_and_manual_assignments(system):
    client,factory = system
    item = next(item for item in catalog(client) if item["name"] == "食譜")
    assert client.patch(f"/api/v1/taxonomy/{item['id']}",json={"version":1,"archived":True}).status_code == 200
    with factory() as session:
        save = session.get(Save,"saved")
        assert session.get(SaveTaxon,(save.id,item["id"]))
        assert validate_assignment(session,save.owner_id,"topic",["食譜"],["食譜"]) == ["食譜"]
        with pytest.raises(ValueError): validate_assignment(session,save.owner_id,"topic",["食譜"])
        assert filter_ai_names(session,save.owner_id,"topic",["食譜","亂造"]) == []
    assert client.patch(f"/api/v1/taxonomy/{item['id']}",json={"version":2,"archived":False}).status_code == 200


def test_dynamic_ai_catalog_and_stale_topic_rejection():
    def response(request):
        payload = json.loads(request.content)
        assert payload["format"]["properties"]["topics"]["items"]["enum"] == ["投資理財"]
        assert "股票" in payload["messages"][0]["content"]
        return httpx.Response(200,json={"message":{"content":json.dumps({"suggested_title":"股票分析","summary":"分析公司","topics":["投資理財"],"tags":[]})}})
    with topic_catalog([{"name":"投資理財","description":"股票"}]):
        result = analyze("分析","內容",[],transport=httpx.MockTransport(response))
        assert result.topics == ["投資理財"]
    with pytest.raises(AIUnavailable):
        analyze("分析","內容",[],transport=httpx.MockTransport(lambda request:httpx.Response(200,json={"message":{"content":json.dumps({"suggested_title":"分析","summary":"","topics":["投資理財"],"tags":[]})}})))


def test_suggestion_worker_never_applies_until_selected_confirmation(system,monkeypatch):
    client,factory = system
    proposals = [{"kind":"new_topic","name":"投資理財","description":"股票","source_ids":[],"target_id":None,"save_ids":["saved"],"reason":"收藏包含投資內容"}]
    monkeypatch.setattr("clueshelf.taxonomy_suggestions.generate",lambda *args:proposals)
    requested = client.post("/api/v1/taxonomy/suggestions").json()
    assert requested["state"] == "queued"
    assert client.post("/api/v1/taxonomy/suggestions").json()["id"] == requested["id"]
    assert run_once(factory)
    assert not any(item["name"]=="投資理財" for item in catalog(client))
    assert client.post(f"/api/v1/taxonomy/suggestions/{requested['id']}/apply",json={"proposal_index":0,"save_ids":["other-owner"]}).status_code == 422
    result = client.post(f"/api/v1/taxonomy/suggestions/{requested['id']}/apply",json={"proposal_index":0,"save_ids":["saved"]})
    assert result.status_code == 200
    with factory() as session:
        save=session.get(Save,"saved")
        assert save.manual_topics == ["食譜","投資理財"]
        assert save.analysis["topics"] == ["食譜"]
    assert client.post(f"/api/v1/taxonomy/suggestions/{requested['id']}/apply",json={"proposal_index":0,"save_ids":["saved"]}).status_code == 409


def test_worker_resolves_catalog_changes_during_ai_without_reviving_source(system, monkeypatch):
    client, factory = system
    from clueshelf.ai import Analysis
    from clueshelf.service import enqueue
    from clueshelf.worker import run_once as run_save
    recipe = next(item for item in catalog(client) if item["name"] == "食譜")
    target = client.post("/api/v1/taxonomy", json={"kind":"topic","name":"飲食"}).json()
    with factory() as session:
        save = session.get(Save,"saved")
        enqueue(session,save,kind="analyze")
        session.commit()
    def model(*args):
        response = client.post(f"/api/v1/taxonomy/{recipe['id']}/merge", json={"version":1,"target_id":target["id"],"target_version":1})
        assert response.status_code == 200
        return Analysis(suggested_title="摘要",summary="內容",topics=["食譜"],tags=["LLM"])
    monkeypatch.setattr("clueshelf.worker.analyze",model)
    assert run_save(factory,lane="ai")
    with factory() as session:
        save=session.get(Save,"saved")
        assert save.analysis["raw_topics"] == ["食譜"]
        assert save.analysis["topics"] == ["飲食"]
        assert session.get(SaveTaxon,(save.id,target["id"]))
        assert not session.get(SaveTaxon,(save.id,recipe["id"]))


def test_batch_catalog_matches_individual_counts_and_aliases(system):
    from clueshelf.taxonomy import catalog_views, item_view
    from sqlalchemy import event
    client, factory = system
    with factory() as session:
        rows = list(session.scalars(select(Taxon).where(Taxon.owner_id == "local-developer")))
        expected = [item_view(session, row) for row in rows]
        statements = []
        def record(*args):
            statements.append(args[2])
        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            actual = catalog_views(session, rows)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert actual == expected
        assert len(statements) == 2
