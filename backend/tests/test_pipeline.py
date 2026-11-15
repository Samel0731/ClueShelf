import time

from sqlalchemy import select

from test_foundation import system, add, URL
from clueshelf.ai import Analysis
from clueshelf.extraction import Comment, ExtractionResult
from clueshelf.models import Job, Save
from clueshelf.worker import claim, finish, renew, run_once


def wire(monkeypatch, result=None):
    monkeypatch.setattr("clueshelf.worker.extract", lambda *args: result or ExtractionResult(original_title="動画タイトル", author_text="作者介紹日本拉麵", status="complete", canonical_url="https://www.youtube.com/watch?v=abcdefghijk"))
    monkeypatch.setattr("clueshelf.worker.analyze", lambda *args: Analysis(suggested_title="京都拉麵", summary="作者內容：介紹拉麵。", topics=["餐廳"], tags=["拉麵"]))


def test_source_then_analysis_and_title_selection(system, monkeypatch):
    client, factory = system
    wire(monkeypatch)
    item = add(client)
    run_once(factory)
    result = client.get(f"/api/v1/saves/{item['id']}").json()
    assert result["title"] == "動画タイトル"
    assert result["author_text"] == "作者介紹日本拉麵"
    assert result["source"]["original_title"] == "動画タイトル"
    assert result["analysis"]["suggested_title"] == "京都拉麵"
    assert result["analysis"]["summary"] == result["author_text"]
    assert result["analysis"]["summary_origin"] == "source"
    assert result["ai_status"] == "complete"
    selected = client.post(f"/api/v1/saves/{item['id']}/title", json={"version": 1, "mode": "ai"})
    assert selected.status_code == 200 and selected.json()["title"] == "京都拉麵"
    assert client.post(f"/api/v1/saves/{item['id']}/title", json={"version": 1, "mode": "original"}).status_code == 409


def test_manual_content_survives_repeated_read(system, monkeypatch):
    client, factory = system
    wire(monkeypatch)
    item = add(client, title="我的標題", author_text="人工正文")
    run_once(factory)
    result = client.get(f"/api/v1/saves/{item['id']}").json()
    assert result["title"] == "我的標題" and result["author_text"] == "人工正文"
    assert result["source"]["author_text"] == "作者介紹日本拉麵"
    wire(monkeypatch, ExtractionResult(status="blocked", reason="登入限制"))
    assert client.post(f"/api/v1/saves/{item['id']}/read", json={"version": 1}).status_code == 200
    run_once(factory)
    result = client.get(f"/api/v1/saves/{item['id']}").json()
    assert result["source"]["author_text"] == "作者介紹日本拉麵"
    assert result["extraction_status"] == "blocked" and result["author_text"] == "人工正文"


def test_edit_during_inference_rejects_old_result(system, monkeypatch):
    client, factory = system
    wire(monkeypatch)
    item = add(client)

    def slow_model(*args):
        assert client.patch(f"/api/v1/saves/{item['id']}", json={"version": 1, "title": "新人工標題"}).status_code == 200
        return Analysis(suggested_title="舊模型標題", summary="舊摘要", topics=["其他"], tags=[])

    monkeypatch.setattr("clueshelf.worker.analyze", slow_model)
    run_once(factory)
    result = client.get(f"/api/v1/saves/{item['id']}").json()
    assert result["title"] == "新人工標題" and result["analysis"] is None and result["status"] == "queued"
    assert result["extraction_status"] not in {"queued", "processing"}


def test_expired_worker_cannot_renew_or_commit(system):
    client, factory = system
    item = add(client)
    job = claim(factory)
    with factory() as s:
        row = s.get(Job, job.id)
        row.lease_until = time.time() - 1
        s.commit()
    assert renew(factory, job) is False
    assert finish(factory, job) is False
    assert client.get(f"/api/v1/saves/{item['id']}").json()["status"] == "processing"


def test_threads_shares_resolve_without_overwriting_original(system, monkeypatch):
    client, factory = system
    canonical = "https://www.threads.com/@someone/post/ABC123"
    wire(monkeypatch, ExtractionResult(author_text="來源正文", status="partial", canonical_url=canonical, comments=[Comment(source_id="reply1", text="留言觀點", likes=8)], comments_ranking="likes", fetched_count=1))
    first = client.post("/api/v1/saves", json={"url": canonical, "title": "原本人工標題"}).json()["save"]
    run_once(factory)
    other = client.post("/api/v1/saves", json={"url": "https://www.threads.com/share/XYZ123/", "author_text": "分享草稿"}).json()["save"]
    run_once(factory)
    alias = client.get(f"/api/v1/saves/{other['id']}").json()
    assert alias["duplicate_of"] == first["id"] and alias["author_text"] == "分享草稿"
    originals = client.get("/api/v1/saves").json()
    assert len(originals) == 2
    assert next(row for row in originals if row["id"] == first["id"])["title"] == "原本人工標題"
    duplicate = client.post("/api/v1/saves", json={"url": "https://www.threads.net/@someone/post/ABC123"}).json()
    assert duplicate["duplicate"] and duplicate["save"]["id"] == first["id"]


def test_manual_thread_comments_remain_separate(system, monkeypatch):
    client, factory = system
    wire(monkeypatch, ExtractionResult(status="blocked"))
    item = client.post("/api/v1/saves", json={"url": "https://www.threads.com/@someone/post/ABC123"}).json()["save"]
    run_once(factory)
    assert client.patch(f"/api/v1/saves/{item['id']}", json={"version": 1, "author_text": "作者說明", "manual_comments": "讀者意見"}).status_code == 200
    received = []
    def model(title, body, comments):
        received.append((body, comments))
        return Analysis(suggested_title="標題", summary="作者內容與留言觀點", topics=["其他"], tags=[])
    monkeypatch.setattr("clueshelf.worker.analyze", model)
    run_once(factory)
    assert received[0][0] == "作者說明"
    assert received[0][1][0].source_id == "manual" and received[0][1][0].text == "讀者意見"
    result = client.get(f"/api/v1/saves/{item['id']}").json()
    assert result["author_text"] == "作者說明" and result["manual_comments"] == "讀者意見"


def test_non_threads_rejects_manual_comments(system):
    client, _ = system
    item = add(client)
    assert client.patch(f"/api/v1/saves/{item['id']}", json={"version": 1, "manual_comments": "不允許"}).status_code == 422


def test_stale_ai_title_not_selectable(system, monkeypatch):
    from clueshelf.ai import AIUnavailable
    client, factory = system
    wire(monkeypatch)
    item = add(client)
    run_once(factory)
    def offline(*args):
        raise AIUnavailable("offline")
    monkeypatch.setattr("clueshelf.worker.analyze", offline)
    client.patch(f"/api/v1/saves/{item['id']}", json={"version": 1, "author_text": "改過的內容"})
    run_once(factory)
    result = client.get(f"/api/v1/saves/{item['id']}").json()
    assert result["analysis"] is not None and result["ai_status"] == "unavailable"
    assert client.post(f"/api/v1/saves/{item['id']}/title", json={"version": 2, "mode": "ai"}).status_code == 422
