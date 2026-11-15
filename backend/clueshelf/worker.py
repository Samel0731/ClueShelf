"""Durable public-source and local-analysis pipeline with fenced writes."""
import argparse
from contextlib import contextmanager
import logging
import threading
import time
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from .ai import MODEL, PROMPT_VERSION, AIUnavailable, analyze, topic_catalog
from .database import database_url, make_engine, session_factory
from .extraction import Comment, extract
from .links import parse_link
from .models import Job, Save, QueueSchedule
from .service import analysis_size
from .search import sync_save

log = logging.getLogger("clueshelf.worker")
LEASE_SECONDS = 60
AI_ROTATION = ("small", "small", "small", "medium", "medium", "large")


def claim(factory, now=None, lane=None):
    now = time.time() if now is None else now
    with factory() as s:
        s.connection().exec_driver_sql("BEGIN IMMEDIATE")
        lane_filter = Job.kind == "pipeline" if lane == "io" else Job.kind.in_(["analyze", "prepare"]) if lane == "ai" else True
        for job in s.scalars(select(Job).where(Job.state == "running", Job.lease_until <= now, lane_filter)):
            job.state = "failed" if job.attempts >= 3 else "queued"
            job.error = "上次處理中斷，工作已恢復。"
            if job.state == "failed":
                values = {"status": "failed", "ai_status": "failed"}
                if job.kind == "pipeline":
                    values["extraction_status"] = "failed"
                s.execute(update(Save).where(Save.id == job.save_id, Save.version == job.version).values(**values))
        s.flush()
        query = select(Job).where(Job.state == "queued", Job.available_at <= now, lane_filter).order_by(Job.available_at, Job.id).limit(1)
        if lane == "ai":
            schedule = s.get(QueueSchedule, "ai")
            if schedule is None:
                schedule = QueueSchedule(name="ai", position=0)
                s.add(schedule)
            job = None
            for offset in range(len(AI_ROTATION)):
                position = (schedule.position + offset) % len(AI_ROTATION)
                job = s.scalar(query.where(Job.size_class == AI_ROTATION[position]))
                if job is not None:
                    schedule.position = (position + 1) % len(AI_ROTATION)
                    break
        else:
            job = s.scalar(query)
        if job is None:
            s.commit()
            return None
        job.state, job.token, job.lease_until = "running", str(uuid4()), now + LEASE_SECONDS
        job.attempts += 1
        s.execute(update(Save).where(Save.id == job.save_id, Save.version == job.version).values(status="processing"))
        s.commit()
        return job


def renew(factory, job):
    now = time.time()
    with factory() as s:
        changed = s.execute(update(Job).where(Job.id == job.id, Job.state == "running", Job.token == job.token, Job.lease_until > now).values(lease_until=now + LEASE_SECONDS)).rowcount
        s.commit()
        return bool(changed)


@contextmanager
def heartbeat(factory, job):
    stop = threading.Event()

    def beat():
        while not stop.wait(10):
            try:
                if not renew(factory, job):
                    return
            except OperationalError:
                log.warning("lease_renewal_failed", extra={"job_id": job.id})

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=12)


def apply_phase(factory, job, operation):
    with factory() as s:
        s.connection().exec_driver_sql("BEGIN IMMEDIATE")
        current = s.scalar(select(Job).where(Job.id == job.id, Job.state == "running", Job.token == job.token, Job.lease_until > time.time()))
        save = s.get(Save, job.save_id) if current else None
        if not current or not save or save.version != job.version:
            return False
        operation(s, save, current)
        sync_save(s, save)
        s.commit()
        return True


def finish(factory, job, *, error=None):
    def complete(s, save, current):
        current.lease_until, current.token = None, None
        if error:
            current.error = error[:500]
            current.state = "failed" if current.attempts >= 3 else "queued"
            current.available_at = time.time() + 2 ** current.attempts
            save.status = "failed" if current.state == "failed" else "queued"
            if current.state == "failed":
                if save.extraction_status in {"processing", "queued"}:
                    save.extraction_status = "failed"
                if save.ai_status in {"processing", "queued"}:
                    save.ai_status = "failed"
        else:
            current.state, current.error = "done", None
            save.status = "ready" if save.author_text.strip() or save.manual_comments.strip() or (save.source or {}).get("comments") else "needs_text"
        save.updated_at = time.time()
    return apply_phase(factory, job, complete)


def apply_source(s, save, result):
    save.extraction_status, save.extraction_error = result.status, result.reason
    if result.author_text or result.original_title or result.comments or not save.source:
        save.source = result.model_dump()
    if not save.text_manual and result.author_text:
        save.author_text = result.author_text
    if not save.title_manual and result.original_title and (save.platform == "youtube" and save.title_mode == "auto" or save.title_mode == "original"):
        save.title = result.original_title
    if not result.canonical_url:
        return
    try:
        platform, identity, canonical = parse_link(result.canonical_url)
    except ValueError:
        return
    if platform != save.platform or identity.startswith("share:"):
        return
    existing = s.scalar(select(Save).where(Save.owner_id == save.owner_id, Save.platform == platform, Save.content_id == identity, Save.id != save.id))
    if existing:
        save.duplicate_of = existing.id
    else:
        save.content_id, save.url = identity, canonical


def snapshot(factory, job):
    with factory() as s:
        save = s.get(Save, job.save_id)
        if save is None or save.version != job.version:
            return None
        return {"platform": save.platform, "url": save.url, "title": save.title, "author_text": save.author_text, "manual_comments": save.manual_comments, "source": save.source or {}, "duplicate_of": save.duplicate_of}


def process(factory, job, lane=None):
    data = snapshot(factory, job)
    if data is None:
        return
    if job.kind == "prepare":
        finish(factory, job)
        return
    if job.kind == "pipeline" and not (data["source"].get("provider") == "youtube_api"):
        if not apply_phase(factory, job, lambda s, save, _: setattr(save, "extraction_status", "processing")):
            return
        result = extract(data["platform"], data["url"])
        if not apply_phase(factory, job, lambda s, save, _: apply_source(s, save, result)):
            return
        data = snapshot(factory, job)
        if data is None:
            return
        if result.status == "failed" and not data["author_text"] and not data["manual_comments"] and not data["source"].get("comments"):
            finish(factory, job, error=result.reason or "來源讀取失敗。")
            return
    if lane == "io":
        def handoff(s, save, current):
            current.kind, current.size_class = "analyze", analysis_size(save)
            current.state, current.attempts = "queued", 0
            current.available_at = time.time()
            current.lease_until, current.token = None, None
            save.status, save.ai_status = "queued", "queued"
        apply_phase(factory, job, handoff)
        return
    if data["duplicate_of"]:
        apply_phase(factory, job, lambda s, save, _: setattr(save, "ai_status", "idle"))
        finish(factory, job)
        return
    comments = [Comment.model_validate(item) for item in data["source"].get("comments", [])] if data["platform"] == "threads" else []
    if data["platform"] == "threads" and data["manual_comments"]:
        comments.insert(0, Comment(source_id="manual", text=data["manual_comments"], likes=None))
    if not data["author_text"] and not comments and not data["source"].get("original_title") and not data["title"]:
        apply_phase(factory, job, lambda s, save, _: setattr(save, "ai_status", "idle"))
        finish(factory, job)
        return
    if not apply_phase(factory, job, lambda s, save, _: setattr(save, "ai_status", "processing")):
        return
    try:
        from .taxonomy import active_topics
        from .service import OWNER
        with factory() as catalog_session:
            topics = active_topics(catalog_session, OWNER)
        with topic_catalog(topics):
            result = analyze(data["source"].get("original_title", data["title"]), data["author_text"], comments)
    except AIUnavailable as error:
        def unavailable(s, save, _):
            save.ai_status, save.ai_error = "unavailable", str(error)
        apply_phase(factory, job, unavailable)
    else:
        def complete(s, save, _):
            from .taxonomy import filter_ai_names
            raw = result.model_dump()
            raw["raw_topics"], raw["raw_tags"] = list(raw["topics"]), list(raw["tags"])
            raw["topics"] = filter_ai_names(s, save.owner_id, "topic", raw["topics"])
            raw["tags"] = filter_ai_names(s, save.owner_id, "tag", raw["tags"])
            save.analysis = {**raw, "model": MODEL, "prompt_version": PROMPT_VERSION, "generated_at": time.time(), "input_version": job.version, "input_truncated": len(data["author_text"]) > 2500 or any(len(c.text) > 100 for c in comments)}
            if data["author_text"].strip() and len(data["author_text"]) < 80 and not comments:
                # Short slang-heavy posts lacked enough context in the real local-model probe.
                save.analysis = {**save.analysis, "summary": data["author_text"], "summary_origin": "source"}
            save.ai_status, save.ai_error = "complete", None
            if not save.title_manual and (save.title_mode == "ai" or save.platform != "youtube" and save.title_mode == "auto"):
                save.title = result.suggested_title
        apply_phase(factory, job, complete)
    finish(factory, job)


def run_once(factory, lane=None):
    if lane == "ai":
        from .taxonomy_suggestions import run_once as suggest_once
        if suggest_once(factory):
            return True
    job = claim(factory, lane=lane)
    if job is None:
        return False
    try:
        with heartbeat(factory, job):
            process(factory, job, lane=lane)
    except Exception:
        log.exception("job_failed", extra={"job_id": job.id})
        finish(factory, job, error="處理發生錯誤，將重試；請檢查 worker 紀錄。")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--lane", choices=("io", "ai"), default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    factory = session_factory(make_engine(database_url()))
    if args.once:
        run_once(factory, lane=args.lane)
        return
    try:
        while True:
            try:
                worked = run_once(factory, lane=args.lane)
            except OperationalError as error:
                if "locked" not in str(error).lower() and "busy" not in str(error).lower():
                    raise
                log.warning("database_busy_retry")
                time.sleep(1)
                continue
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
