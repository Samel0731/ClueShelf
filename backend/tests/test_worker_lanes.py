import time
from uuid import uuid4

from sqlalchemy import select

from test_foundation import system, add
from clueshelf.ai import Analysis
from clueshelf.extraction import Comment, ExtractionResult
from clueshelf.models import Job, Save
from clueshelf.service import analysis_size, enqueue
from clueshelf.worker import claim, finish, run_once


def test_io_handoff_does_not_run_ai(system, monkeypatch):
    client, factory = system
    item = add(client)
    monkeypatch.setattr("clueshelf.worker.extract", lambda *args: ExtractionResult(original_title="title", author_text="食譜" * 1200, status="complete"))
    def unexpected(*args):
        raise AssertionError("IO lane must never run AI")
    monkeypatch.setattr("clueshelf.worker.analyze", unexpected)
    assert run_once(factory, lane="io")
    with factory() as s:
        job = s.scalar(select(Job).where(Job.save_id == item["id"]))
        assert job.kind == "analyze" and job.size_class == "medium"
        assert job.state == "queued" and job.attempts == 0
    assert not run_once(factory, lane="io")
    monkeypatch.setattr("clueshelf.worker.analyze", lambda *args: Analysis(suggested_title="食譜", summary="食譜", topics=["食譜"], tags=[]))
    assert run_once(factory, lane="ai")
    assert client.get(f"/api/v1/saves/{item['id']}").json()["ai_status"] == "complete"


def test_ai_lane_never_reads_sources(system, monkeypatch):
    client, factory = system
    add(client)
    assert not run_once(factory, lane="ai")


def test_official_source_legacy_pipeline_handoff_never_runs_ai(system, monkeypatch):
    client, factory = system
    item = add(client)
    with factory() as s:
        save = s.get(Save, item["id"])
        save.source = {"provider": "youtube_api", "original_title": "official"}
        save.extraction_status = "complete"
        s.commit()
    def unexpected(*args):
        raise AssertionError("IO must not scrape official metadata or call AI")
    monkeypatch.setattr("clueshelf.worker.extract", unexpected)
    monkeypatch.setattr("clueshelf.worker.analyze", unexpected)
    assert run_once(factory, lane="io")
    with factory() as s:
        job = s.scalar(select(Job).where(Job.save_id == item["id"]))
        assert job.kind == "analyze" and job.state == "queued"
        assert s.get(Save, item["id"]).extraction_status == "complete"


def test_expired_ai_lease_preserves_official_source_status(system):
    client, factory = system
    item = add(client)
    with factory() as s:
        job = s.scalar(select(Job).where(Job.save_id == item["id"]))
        job.kind, job.state, job.attempts = "analyze", "running", 3
        job.lease_until = time.time() - 1
        s.get(Save, item["id"]).extraction_status = "complete"
        s.commit()
    assert claim(factory, lane="ai") is None
    with factory() as s:
        assert s.get(Save, item["id"]).extraction_status == "complete"


def test_official_read_enqueue_uses_ai_only(system):
    client, factory = system
    item = add(client)
    with factory() as s:
        save = s.get(Save, item["id"])
        save.source = {"provider": "youtube_api", "original_title": "官方標題"}
        save.extraction_status = "complete"
        save.version += 1
        enqueue(s, save, kind="pipeline")
        s.commit()
        job = s.scalar(select(Job).where(Job.save_id == save.id, Job.version == save.version))
        assert job.kind == "analyze" and save.extraction_status == "complete"


def test_weighted_rotation_persists_and_fifo(system):
    _, factory = system
    created = {size: [] for size in ("small", "medium", "large")}
    now = time.time()
    with factory() as s:
        for size in created:
            for number in range(6):
                save = Save(id=str(uuid4()), owner_id="local-developer", platform="youtube", content_id=str(uuid4()), url="https://www.youtube.com/", title="title", author_text="body", created_at=now, updated_at=now)
                s.add(save)
                s.flush()
                enqueue(s, save, kind="analyze")
                s.flush()
                job = s.scalar(select(Job).where(Job.save_id == save.id))
                job.size_class, job.available_at = size, now + number * .001
                created[size].append(job.id)
        s.commit()
    sequence = []
    for _ in range(12):
        job = claim(factory, now=now+1, lane="ai")
        sequence.append(job.size_class)
        assert job.id == created[job.size_class].pop(0)
        assert finish(factory, job)
    assert sequence == ["small", "small", "small", "medium", "medium", "large"] * 2


def test_actual_excerpt_size_and_threads_only_comments():
    save = Save(platform="youtube", title="a" * 10000, author_text="b" * 10000, source={}, manual_comments="x" * 10000)
    assert analysis_size(save) == "medium"  # 300 title + 2500 body.
    save.platform = "threads"
    save.source = {"comments": [Comment(source_id=str(i), text="c" * 1000, likes=1).model_dump() for i in range(20)]}
    assert analysis_size(save) == "large"  # Adds eleven 100-character excerpts.
